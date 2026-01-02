from rest_framework import viewsets, permissions, status, generics, filters  # <--- Added 'filters'
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from .models import Post, Friendship, Like, Comment, User, Notification
from .serializers import UserProfileSerializer, PostSerializer, FriendshipSerializer, CommentSerializer, RegisterSerializer, NotificationSerializer
from .permissions import IsOwnerOrReadOnly

User = get_user_model()

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    # Added search capability to users too (optional but good)
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'email']

    @action(detail=False, methods=['get'])
    def me(self, request):
        """
        GET /api/users/me/
        Returns the profile of the currently logged-in user.
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def posts(self, request, pk=None):
        """
        Returns all posts belonging to a specific user.
        URL: /api/users/{pk}/posts/
        """
        user = self.get_object()
        # Fetch posts where author is this user, ordered by newest first
        posts = Post.objects.filter(author=user).order_by('-created_at')
        
        # Serialize and return
        serializer = PostSerializer(posts, many=True, context={'request': request})
        return Response(serializer.data)

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all()
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    # --- FIX: Search Configuration ---
    filter_backends = [filters.SearchFilter]
    search_fields = ['caption', 'author__username']
    # ---------------------------------

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def get_queryset(self):
        queryset = Post.objects.all().order_by('-created_at')

        # Get params from the URL (e.g., ?lat=24.1&lng=121.5&radius=0.5)
        lat = self.request.query_params.get('lat')
        lng = self.request.query_params.get('lng')
        
        # Default to 0.5km (500m) if not specified
        radius_km = self.request.query_params.get('radius', 0.5) 

        if lat and lng:
            try:
                user_location = Point(float(lng), float(lat), srid=4326)
                
                # 1. Filter: Keep only posts within radius
                queryset = queryset.filter(location__distance_lte=(user_location, D(km=radius_km)))
                
                # 2. Annotate: Calculate exact distance for display
                queryset = queryset.annotate(
                    distance=Distance('location', user_location)
                ).order_by('distance')
                
            except (ValueError, TypeError):
                pass # Ignore invalid coords
        
        return queryset

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        """
        Endpoint: POST /api/posts/{id}/like/
        """
        post = self.get_object()
        user = request.user
        
        # Check if already liked
        existing_like = Like.objects.filter(post=post, user=user).first()
        
        if existing_like:
            # User wants to UNLIKE
            existing_like.delete()
            liked = False
        else:
            # User wants to LIKE
            Like.objects.create(post=post, user=user)
            liked = True
            
        return Response({
            'status': 'success', 
            'is_liked': liked,
            'like_count': post.likes.count()
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='comments')
    def create_comment(self, request, pk=None):
        """
        Endpoint: POST /api/posts/{id}/comments/
        """
        post = self.get_object()
        
        # Use Serializer for validation instead of manual extraction
        # Context is passed so the serializer can access request.user if needed
        serializer = CommentSerializer(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            serializer.save(author=request.user, post=post)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class FeedViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Returns posts ordered by distance (if lat/lon provided) or time.
    Usage: /api/feed/?latitude=12.34&longitude=56.78
    """
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Post.objects.all()
        lat = self.request.query_params.get('latitude')
        lon = self.request.query_params.get('longitude')

        if lat and lon:
            try:
                user_location = Point(float(lon), float(lat), srid=4326)
                # Annotate with distance and order by it
                return queryset.annotate(
                    distance=Distance('location', user_location)
                ).order_by('distance')
            except (ValueError, TypeError):
                pass # Fallback to time ordering if invalid floats
        
        return queryset.order_by('-created_at')

class FriendRequestViewSet(viewsets.ModelViewSet):
    serializer_class = FriendshipSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Return requests involving the current user
        user = self.request.user
        return Friendship.objects.filter(to_user=user) | Friendship.objects.filter(from_user=user)

    def perform_create(self, serializer):
        serializer.save(from_user=self.request.user)

class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        post_id = self.request.query_params.get('post_id')
        if post_id:
            queryset = queryset.filter(post_id=post_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    # Explicit Update Check: Only Author can Edit
    def update(self, request, *args, **kwargs):
        comment = self.get_object()
        if comment.author != request.user:
            return Response({'error': 'You can only edit your own comments'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    # Explicit Destroy Check: Only Author can Delete
    def destroy(self, request, *args, **kwargs):
        comment = self.get_object()
        if comment.author != request.user:
            return Response({'error': 'You can only delete your own comments'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)
    
class NotificationViewSet(viewsets.ModelViewSet): 
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options'] # Optional: Restrict methods if needed

    def get_queryset(self):
        # Only show notifications for the logged-in user
        return Notification.objects.filter(recipient=self.request.user)

    @action(detail=False, methods=['post'])
    def mark_read(self, request):
        notifications = self.get_queryset().filter(is_read=False)
        notifications.update(is_read=True)
        return Response({'status': 'marked as read'})