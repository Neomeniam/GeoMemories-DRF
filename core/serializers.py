from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.db.models import Q
# 1. ADD PostMedia to imports
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
    friends_count = serializers.SerializerMethodField() # <--- NEW
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
        if user == obj:
            return 'self'

        friends = Friendship.objects.filter(
            (Q(from_user=user, to_user=obj) | Q(from_user=obj, to_user=user)),
            status='accepted'
        ).exists()
        if friends:
            return 'friends'

        sent_request = Friendship.objects.filter(from_user=user, to_user=obj, status='pending').exists()
        if sent_request:
            return 'sent'

        received_request = Friendship.objects.filter(from_user=obj, to_user=user, status='pending').exists()
        if received_request:
            return 'received'

        return 'none'

    def get_friend_request_id(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        friend_request = Friendship.objects.filter(
            from_user=obj,
            to_user=request.user,
            status='pending'
        ).first()
        return friend_request.id if friend_request else None
    
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
    
    # --- NEW FIELDS ---
    is_liked = serializers.SerializerMethodField()
    like_count = serializers.ReadOnlyField()
    replies = serializers.SerializerMethodField() 

    parent = serializers.PrimaryKeyRelatedField(queryset=Comment.objects.all(), required=False, allow_null=True)
    
    class Meta:
        model = Comment
        fields = [
            'id', 'post', 'author', 'text', 'created_at', 
            'is_owner', 'parent', 'is_liked', 'like_count', 'replies'
        ]
        read_only_fields = ['id', 'created_at', 'author', 'post', 'likes']

    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.author == request.user
        return False

    # Check if current user liked this comment
    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(id=request.user.id).exists()
        return False

    # Recursive: Fetch replies for this comment
    def get_replies(self, obj):
        # Optimization: Only fetch replies for top-level comments to prevent deep nesting performance hits
        if obj.parent is None:
            serializer = CommentSerializer(obj.replies.all(), many=True, context=self.context)
            return serializer.data
        return []
    
# 2. NEW SERIALIZER: Handles individual photos/videos
class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = ['id', 'file', 'media_type']


class PostSerializer(serializers.ModelSerializer):
    author = UserProfileSerializer(read_only=True)
    # 1. NEW FIELDS: These act as the "interface" for the Android app
    latitude = serializers.FloatField(required=False, allow_null=True, write_only=True) 
    longitude = serializers.FloatField(required=False, allow_null=True, write_only=True)
    
    # Existing fields
    like_count = serializers.IntegerField(source='likes.count', read_only=True)
    comment_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)
    is_owner = serializers.SerializerMethodField()
    media = PostMediaSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        # 2. UPDATE FIELDS LIST: Add 'latitude' and 'longitude' so they are accepted
        fields = [
            'id', 'author', 'caption', 'media', 'created_at', 
            'like_count', 'comment_count', 'is_liked', 'comments', 'is_owner',
            'visibility', 'location_access',
            'latitude', 'longitude' # <--- ADDED
        ]
        read_only_fields = ['id', 'created_at', 'author']

    # 3. READ: Convert Database Point -> Android Numbers
    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Manually inject lat/lng into the JSON response
        if instance.location:
            data['latitude'] = instance.location.y
            data['longitude'] = instance.location.x
        else:
            data['latitude'] = None
            data['longitude'] = None
        return data

    # 4. WRITE: Convert Android Numbers -> Database Point
    def create(self, validated_data):
        # Extract the numbers
        lat = validated_data.pop('latitude', None)
        lng = validated_data.pop('longitude', None)

        # Build the Point object
        if lat is not None and lng is not None:
            try:
                validated_data['location'] = Point(float(lng), float(lat))
            except (ValueError, TypeError):
                pass 

        # Proceed with standard creation
        return super().create(validated_data)

    # --- Your Existing Helper Methods ---
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
        # FIX: Ensure this .filter(parent=None) is present!
        # If you miss this filter, replies show up twice.
        qs = obj.comments.filter(parent=None).order_by('-created_at')[:3] # Limit to 3 for preview, or remove slice for full list
        return CommentSerializer(qs, many=True, context=self.context).data

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