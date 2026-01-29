from rest_framework import viewsets, permissions, status, generics, filters
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.db.models import Q  
from .models import Post, PostMedia, Friendship, Like, Comment, User, Notification
# IMPORT PostDetailSerializer
from .serializers import UserProfileSerializer, PostSerializer, PostDetailSerializer, FriendshipSerializer, CommentSerializer, RegisterSerializer, NotificationSerializer
from .permissions import IsOwnerOrReadOnly

User = get_user_model()

def get_friend_ids(user):
    if not user.is_authenticated: return []
    sent = Friendship.objects.filter(from_user=user, status='accepted').values_list('to_user_id', flat=True)
    received = Friendship.objects.filter(to_user=user, status='accepted').values_list('from_user_id', flat=True)
    return set(list(sent) + list(received))

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'email']

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        user = request.user
        if request.method == 'GET':
            serializer = self.get_serializer(user)
            return Response(serializer.data)
        elif request.method == 'PATCH':
            serializer = self.get_serializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def posts(self, request, pk=None):
        target_user = self.get_object()
        requesting_user = request.user
        queryset = Post.objects.filter(author=target_user).order_by('-created_at')
        if requesting_user != target_user:
            friend_ids = get_friend_ids(requesting_user)
            is_friend = target_user.id in friend_ids
            if is_friend:
                queryset = queryset.filter(Q(visibility='public') | Q(visibility='friends'))
            else:
                queryset = queryset.filter(visibility='public')
        serializer = PostSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)
        
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all()
    # REMOVED default serializer_class here to use get_serializer_class
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['caption', 'author__username']

    # --- NEW: Switch Serializers ---
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PostDetailSerializer
        return PostSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = serializer.save(author=request.user)
        files = request.FILES.getlist('media_files')
        for f in files:
            media_type = 'video' if 'video' in f.content_type else 'image'
            PostMedia.objects.create(post=post, file=f, media_type=media_type)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def get_queryset(self):
        user = self.request.user
        queryset = Post.objects.all().order_by('-created_at')
        public_q = Q(visibility='public')
        private_q = Q(visibility='private', author=user)
        friend_ids = get_friend_ids(user)
        friends_q = Q(visibility='friends') & (Q(author=user) | Q(author__id__in=friend_ids))
        queryset = queryset.filter(public_q | private_q | friends_q)

        lat = self.request.query_params.get('lat')
        lng = self.request.query_params.get('lng')
        user_location = None
        if lat and lng:
            try:
                user_location = Point(float(lng), float(lat), srid=4326)
            except (ValueError, TypeError): pass

        if user_location:
            cond_author = Q(author=user)
            cond_anywhere = Q(location_access='anywhere')
            cond_nearby_unlocked = Q(location_access='nearby', location__distance_lte=(user_location, D(km=0.5)))
            queryset = queryset.filter(cond_author | cond_anywhere | cond_nearby_unlocked)
            queryset = queryset.annotate(distance=Distance('location', user_location)).order_by('distance')
        else:
            queryset = queryset.filter(Q(author=user) | Q(location_access='anywhere'))
        return queryset

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        post = self.get_object()
        user = request.user
        existing_like = Like.objects.filter(post=post, user=user).first()
        if existing_like:
            existing_like.delete()
            liked = False
        else:
            Like.objects.create(post=post, user=user)
            liked = True
        return Response({'status': 'success', 'is_liked': liked, 'like_count': post.likes.count()})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='comments')
    def create_comment(self, request, pk=None):
        post = self.get_object()
        serializer = CommentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(author=request.user, post=post)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class FeedViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Post.objects.all().order_by('-created_at')
        public_q = Q(visibility='public')
        private_q = Q(visibility='private', author=user)
        friend_ids = get_friend_ids(user)
        friends_q = Q(visibility='friends') & (Q(author=user) | Q(author__id__in=friend_ids))
        queryset = queryset.filter(public_q | private_q | friends_q)
        lat = self.request.query_params.get('latitude')
        lon = self.request.query_params.get('longitude')
        user_location = None
        if lat and lon:
            try:
                user_location = Point(float(lon), float(lat), srid=4326)
            except (ValueError, TypeError): pass
        if user_location:
            cond_author = Q(author=user)
            cond_anywhere = Q(location_access='anywhere')
            cond_nearby_unlocked = Q(location_access='nearby', location__distance_lte=(user_location, D(km=0.5)))
            queryset = queryset.filter(cond_author | cond_anywhere | cond_nearby_unlocked)
            queryset = queryset.annotate(distance=Distance('location', user_location)).order_by('distance')
        else:
            queryset = queryset.filter(Q(author=user) | Q(location_access='anywhere'))
        return queryset

class FriendRequestViewSet(viewsets.ModelViewSet):
    serializer_class = FriendshipSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Friendship.objects.filter(to_user=user) | Friendship.objects.filter(from_user=user)

    def perform_create(self, serializer):
        serializer.save(from_user=self.request.user, status='pending')

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        friend_request = self.get_object()
        if friend_request.to_user != request.user:
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        friend_request.status = 'accepted'
        friend_request.save()
        # Clean up
        Notification.objects.filter(recipient=request.user, sender=friend_request.from_user, type='friend_request').delete()
        return Response({'status': 'accepted'})

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        friend_request = self.get_object()
        if friend_request.to_user != request.user:
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        friend_request.status = 'rejected'
        friend_request.save()
        # Clean up
        Notification.objects.filter(recipient=request.user, sender=friend_request.from_user, type='friend_request').delete()
        return Response({'status': 'declined'})

class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        post_id = self.request.query_params.get('post_id')
        if post_id:
            queryset = queryset.filter(post_id=post_id, parent=None)
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def update(self, request, *args, **kwargs):
        comment = self.get_object()
        if comment.author != request.user: return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        comment = self.get_object()
        if comment.author != request.user: return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def like(self, request, pk=None):
        comment = self.get_object()
        user = request.user
        if comment.likes.filter(id=user.id).exists():
            comment.likes.remove(user)
            liked = False
        else:
            comment.likes.add(user)
            liked = True
        return Response({'status': 'success', 'is_liked': liked, 'like_count': comment.like_count})
    
    
class NotificationViewSet(viewsets.ModelViewSet): 
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        # SELF-CLEANING LOGIC
        user = self.request.user
        notifications = Notification.objects.filter(recipient=user)
        stale_ids = []
        for notif in notifications:
            if notif.type == 'friend_request':
                # Check if request is still pending
                is_pending = Friendship.objects.filter(
                    from_user=notif.sender,
                    to_user=user,
                    status='pending'
                ).exists()
                if not is_pending:
                    stale_ids.append(notif.id)
        
        if stale_ids:
            Notification.objects.filter(id__in=stale_ids).delete()
            
        return Notification.objects.filter(recipient=user).order_by('-created_at')

    @action(detail=False, methods=['post'])
    def mark_read(self, request):
        notifications = self.get_queryset().filter(is_read=False)
        notifications.update(is_read=True)
        return Response({'status': 'marked as read'})