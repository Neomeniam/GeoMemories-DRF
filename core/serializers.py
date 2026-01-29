from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.db.models import Q
from .models import Post, PostMedia, Friendship, Comment, Notification 

User = get_user_model()

class LocationField(serializers.Field):
    def to_representation(self, value):
        return {"latitude": value.y, "longitude": value.x}

    def to_internal_value(self, data):
        try:
            return Point(float(data['longitude']), float(data['latitude']), srid=4326)
        except (KeyError, ValueError, TypeError):
            raise serializers.ValidationError("Invalid location.")

class UserProfileSerializer(serializers.ModelSerializer):
    post_count = serializers.SerializerMethodField()
    friends_count = serializers.SerializerMethodField()
    friendship_status = serializers.SerializerMethodField()
    friend_request_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'bio', 'avatar', 'post_count', 'friends_count', 'friendship_status', 'friend_request_id']

    def get_post_count(self, obj):
        return obj.post_set.count()

    def get_friends_count(self, obj):
        return Friendship.objects.filter(
            (Q(from_user=obj) | Q(to_user=obj)) & Q(status='accepted')
        ).count()

    def get_friendship_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 'none'
        user = request.user
        if user == obj: return 'self'
        if Friendship.objects.filter((Q(from_user=user, to_user=obj) | Q(from_user=obj, to_user=user)), status='accepted').exists():
            return 'friends'
        if Friendship.objects.filter(from_user=user, to_user=obj, status='pending').exists():
            return 'sent'
        if Friendship.objects.filter(from_user=obj, to_user=user, status='pending').exists():
            return 'received'
        return 'none'

    def get_friend_request_id(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated: return None
        fr = Friendship.objects.filter(from_user=obj, to_user=request.user, status='pending').first()
        return fr.id if fr else None
    
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    class Meta:
        model = User
        fields = ['username', 'password', 'email']
        extra_kwargs = {'email': {'required': True}}
    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )

class CommentSerializer(serializers.ModelSerializer):
    author = UserProfileSerializer(read_only=True)
    is_owner = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    like_count = serializers.ReadOnlyField()
    replies = serializers.SerializerMethodField() 
    parent = serializers.PrimaryKeyRelatedField(queryset=Comment.objects.all(), required=False, allow_null=True)
    
    class Meta:
        model = Comment
        fields = ['id', 'post', 'author', 'text', 'created_at', 'is_owner', 'parent', 'is_liked', 'like_count', 'replies']
        read_only_fields = ['id', 'created_at', 'author', 'post', 'likes']

    def get_is_owner(self, obj):
        request = self.context.get('request')
        return request and request.user.is_authenticated and obj.author == request.user

    def get_is_liked(self, obj):
        request = self.context.get('request')
        return request and request.user.is_authenticated and obj.likes.filter(id=request.user.id).exists()

    def get_replies(self, obj):
        # Stop recursion: Level 2 max
        if obj.parent is not None:
            return []
        serializer = CommentSerializer(obj.replies.all(), many=True, context=self.context)
        return serializer.data
    
class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = ['id', 'file', 'media_type']


# --- BASE SERIALIZER (For Feed) ---
class PostSerializer(serializers.ModelSerializer):
    author = UserProfileSerializer(read_only=True)
    latitude = serializers.FloatField(required=False, allow_null=True, write_only=True) 
    longitude = serializers.FloatField(required=False, allow_null=True, write_only=True)
    
    like_count = serializers.IntegerField(source='likes.count', read_only=True)
    comment_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    # comments field REMOVED from base serializer (Feed doesn't need tree)
    is_owner = serializers.SerializerMethodField()
    media = PostMediaSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            'id', 'author', 'caption', 'media', 'created_at', 
            'like_count', 'comment_count', 'is_liked', 'is_owner',
            'visibility', 'location_access',
            'latitude', 'longitude'
        ]
        read_only_fields = ['id', 'created_at', 'author']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.location:
            data['latitude'] = instance.location.y
            data['longitude'] = instance.location.x
        else:
            data['latitude'] = None
            data['longitude'] = None
        return data

    def create(self, validated_data):
        lat = validated_data.pop('latitude', None)
        lng = validated_data.pop('longitude', None)
        if lat is not None and lng is not None:
            try:
                validated_data['location'] = Point(float(lng), float(lat))
            except (ValueError, TypeError):
                pass 
        return super().create(validated_data)

    def get_comment_count(self, obj):
        return obj.comments.count()

    def get_is_liked(self, obj):
        request = self.context.get('request')
        return request and request.user.is_authenticated and obj.likes.filter(user=request.user).exists()

    def get_is_owner(self, obj):
        request = self.context.get('request')
        return request and request.user.is_authenticated and obj.author == request.user


# --- DETAIL SERIALIZER (For Single Post View) ---
class PostDetailSerializer(PostSerializer):
    # This field MUST be a MethodField to use get_comments logic
    comments = serializers.SerializerMethodField()

    class Meta(PostSerializer.Meta):
        fields = PostSerializer.Meta.fields + ['comments']

    def get_comments(self, obj):
        # THIS IS THE FIX: Filter parent=None to stop duplicates
        qs = obj.comments.filter(parent=None).order_by('-created_at')
        return CommentSerializer(qs, many=True, context=self.context).data


class FriendshipSerializer(serializers.ModelSerializer):
    from_user = UserProfileSerializer(read_only=True)
    to_user = UserProfileSerializer(read_only=True)
    to_user_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), source='to_user', write_only=True)

    class Meta:
        model = Friendship
        fields = ['id', 'from_user', 'to_user', 'to_user_id', 'status', 'created_at']
        read_only_fields = ['status']

class NotificationSerializer(serializers.ModelSerializer):
    sender = UserProfileSerializer(read_only=True)
    post = PostSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = ['id', 'sender', 'type', 'post', 'is_read', 'created_at']