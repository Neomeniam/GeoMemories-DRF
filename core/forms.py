from django.forms import ModelForm, HiddenInput
from .models import Post
from django.contrib.auth.models import User

class PostForm(ModelForm):
    class Meta:
        model = Post
        fields = ['caption', 'photo', 'latitude', 'longitude']
        widgets = {
            'latitude': HiddenInput(),
            'longitude': HiddenInput(),
        }

class UserForm(ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email']