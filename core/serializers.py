from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.db.models import Q  # <--- NEW IMPORT needed for queries
from .models import Post, Friendship, Comment, Notification

User = get_user_model()

class LocationField(serializers.Field):
    def to_representation(self, value):
        return {"latitude": value.y, "longitude": value.x}

    def to_internal_value(self, data):
        try:
            return Point(float(data['longitude']), float(data['latitude']), srid=4326)
        except (KeyError, ValueError, TypeError):
            raise serializers.ValidationError("Invalid location. Expected {'latitude': float, 'longitude': float}")

class UserProfileSerializer(serializers.ModelSerializer):
    post_count = serializers.SerializerMethodField()
    friendship_status = serializers.SerializerMethodField() # <--- NEW FIELD

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'bio', 'avatar', 'post_count', 'friendship_status'] # <--- Added to fields

    def get_post_count(self, obj):
        return obj.post_set.count()

    def get_friendship_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 'none'
        
        user = request.user
        if user == obj:
            return 'self'

        # 1. Check if they are already friends (Status = accepted)
        # We check both directions (User A -> User B OR User B -> User A)
        friends = Friendship.objects.filter(
            (Q(from_user=user, to_user=obj) | Q(from_user=obj, to_user=user)),
            status='accepted'
        ).exists()
        if friends:
            return 'friends'

        # 2. Check if I sent a request (Status = pending)
        sent_request = Friendship.objects.filter(
            from_user=user, 
            to_user=obj, 
            status='pending'
        ).exists()
        if sent_request:
            return 'sent'

        # 3. Check if they sent me a request (Status = pending)
        received_request = Friendship.objects.filter(
            from_user=obj, 
            to_user=user, 
            status='pending'
        ).exists()
        if received_request:
            return 'received'

        return 'none'

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

    class Meta:
        model = Comment
        fields = ['id', 'post', 'author', 'text', 'created_at', 'is_owner']
        read_only_fields = ['id', 'created_at', 'author', 'post']

    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.author == request.user
        return False

class PostSerializer(serializers.ModelSerializer):
    author = UserProfileSerializer(read_only=True)
    location = LocationField(required=False, allow_null=True)
    like_count = serializers.IntegerField(source='likes.count', read_only=True)
    comment_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = ['id', 'author', 'caption', 'image', 'location', 'created_at', 'like_count', 'comment_count', 'is_liked', 'comments', 'is_owner']
        read_only_fields = ['id', 'created_at', 'author']

    def get_like_count(self, obj):
        return obj.likes.count()

    def get_comment_count(self, obj):
        return obj.comments.count()

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_comments(self, obj):
        qs = obj.comments.all().order_by('-created_at')[:3]
        return CommentSerializer(qs, many=True).data

    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.author == request.user
        return False

class FriendshipSerializer(serializers.ModelSerializer):
    from_user = UserProfileSerializer(read_only=True)
    to_user = UserProfileSerializer(read_only=True)
    to_user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='to_user', write_only=True
    )

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