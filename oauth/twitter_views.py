import json
from django.views import View
from django.shortcuts import redirect, render
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse
from django.contrib.auth import logout
from django.utils import timezone
import requests
import base64
import hashlib
import os
from .models import UserProfile, OAuthToken, PostStatus
from .config import OAUTH_CONFIG
from django.contrib import messages

class TwitterLoginView(View):
    """
    Initiates the Twitter OAuth 2.0 Authorization Code Flow with PKCE
    """
    def get(self, request):
        # Generate code verifier and challenge for PKCE
        code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode('utf-8')
        code_verifier = code_verifier.replace('=', '')
        
        code_challenge = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).decode('utf-8')
        code_challenge = code_challenge.replace('=', '')
        
        # Store code_verifier in session for later use
        request.session['twitter_code_verifier'] = code_verifier
        
        # Prepare OAuth parameters
        config = OAUTH_CONFIG['twitter']
        params = {
            'response_type': 'code',
            'client_id': config['client_id'],
            'redirect_uri': config['redirect_uri'],
            'scope': ' '.join(config['scopes']),
            'state': os.urandom(16).hex(),
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }
        
        # Store state in session to prevent CSRF
        request.session['twitter_oauth_state'] = params['state']
        
        # Build authorization URL with query parameters
        auth_url = config['authorization_url']
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        authorization_url = f"{auth_url}?{query_string}"
        
        return redirect(authorization_url)


class TwitterCallbackView(View):
    """
    Handles the callback from Twitter OAuth and exchanges the code for access token
    """
    def get(self, request):
        # Store request for use in other methods
        self.request = request
        
        error = request.GET.get('error')
        if error:
            return JsonResponse({'error': error}, status=400)
        
        code = request.GET.get('code')
        state = request.GET.get('state')
        
        # Verify state to prevent CSRF attacks
        stored_state = request.session.get('twitter_oauth_state')
        if not stored_state or state != stored_state:
            return JsonResponse({'error': 'Invalid state parameter'}, status=400)
        
        # Get code verifier from session
        code_verifier = request.session.get('twitter_code_verifier')
        if not code_verifier:
            return JsonResponse({'error': 'Missing code verifier'}, status=400)
        
        # Exchange code for access token
        config = OAUTH_CONFIG['twitter']
        token_data = {
            'code': code,
            'grant_type': 'authorization_code',
            'client_id': config['client_id'],
            'redirect_uri': config['redirect_uri'],
            'code_verifier': code_verifier
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        # use Basic Auth with client_id:client_secret
        if config.get('client_secret'):
            auth_string = f"{config['client_id']}:{config['client_secret']}"
            encoded_auth = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
            headers['Authorization'] = f"Basic {encoded_auth}"

            if 'client_secret' in token_data:
                del token_data['client_secret']
        
        # Log request details for debugging
        print(f"Token URL: {config['token_url']}")
        print(f"Headers: {headers}")
        print(f"Data: {token_data}")
        
        response = requests.post(
            config['token_url'],
            data=token_data,
            headers=headers
        )
        
        # Log response for debugging
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")
        
        if response.status_code != 200:
            return JsonResponse({'error': f'Token exchange failed: {response.text}'}, status=400)
        
        token_info = response.json()
        
        # Get user info from Twitter API
        user_info = self._get_twitter_user_info(token_info['access_token'])
        
        if not user_info:
            return JsonResponse({'error': 'Failed to retrieve user information'}, status=400)
        
        # Save user and token information
        user_profile = self._get_or_create_user_profile(user_info)
        
        self._save_oauth_token(
            user_profile=user_profile,
            provider='twitter',
            provider_user_id=user_info.get('id'),
            access_token=token_info['access_token'],
            refresh_token=token_info.get('refresh_token'),
            expires_in=token_info.get('expires_in'),
            scope=token_info.get('scope')
        )
        
        request.session['user_id'] = user_profile.user.id
        
        if 'twitter_code_verifier' in request.session:
            del request.session['twitter_code_verifier']
        if 'twitter_oauth_state' in request.session:
            del request.session['twitter_oauth_state']
        
        return redirect('dashboard')
    
    def _get_twitter_user_info(self, access_token):
        """
        Get user information from Twitter API
        """
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        
        response = requests.get(
            'https://api.twitter.com/2/users/me',
            headers=headers,
            params={'user.fields': 'name,username,profile_image_url'}
        )
        
        print(f"User Info Response: {response.status_code}")
        print(f"User Info Body: {response.text}")
        
        if response.status_code != 200:
            return None
        
        return response.json().get('data')
    
    def _get_or_create_user_profile(self, user_info):
        """
        Associate Twitter account with the current logged-in user
        instead of creating a new user
        """
        if self.request.user.is_authenticated:
            try:
                user_profile = UserProfile.objects.get(user=self.request.user)
                print(f"Using existing user profile (ID={user_profile.id}) for Twitter connection")
                return user_profile
            except UserProfile.DoesNotExist:
                print(f"User is authenticated but profile not found for user ID {self.request.user.id}")
        else:
            print("Warning: User not authenticated when connecting Twitter account")
    
        email = f"{user_info.get('username')}@twitter.placeholder"
        
        try:
            user_profile = UserProfile.objects.get(email=email)
            print(f"Found user profile by Twitter email placeholder: {email}")
        except UserProfile.DoesNotExist:
            from django.contrib.auth.models import User
            username = f"twitter_{user_info.get('id')}"
            
            user = User.objects.create_user(
                username=username,
                email=email,
                password=os.urandom(16).hex()
            )
            
            user_profile = UserProfile.objects.create(
                user=user,
                name=user_info.get('name', ''),
                email=email
            )
            print(f"Created new user profile (ID={user_profile.id}) for Twitter user {username}")
        
        return user_profile
    
    def _save_oauth_token(self, user_profile, provider, provider_user_id, 
                        access_token, refresh_token=None, expires_in=None, scope=None):
        """
        Save or update OAuth token information securely.
        """
        expires_at = None
        if expires_in:
            expires_at = timezone.now() + timezone.timedelta(seconds=int(expires_in))

        try:
            token, created = OAuthToken.objects.get_or_create(
                user=user_profile,
                provider=provider,
                defaults={
                    'provider_user_id': provider_user_id,
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'expires_at': expires_at,
                    'scope': scope
                }
            )

            if not created:
                # Update existing token
                token.provider_user_id = provider_user_id
                token.access_token = access_token
                if refresh_token:
                    token.refresh_token = refresh_token
                token.expires_at = expires_at
                token.scope = scope
                token.save()

            # Debugging: Confirm token is saved
            print(f"OAuth Token saved: {token.access_token[:10]}... for user_profile ID={user_profile.id}")

        except Exception as e:
            print(f"Error saving OAuth token: {str(e)}")


class TwitterPostView(View):
    """
    Posts a tweet using the user's Twitter OAuth token
    """
    # Twitter's character limit
    TWITTER_CHAR_LIMIT = 280
    
    def get(self, request):
        return render(request, 'dashboard')
        
    def post(self, request):
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                content = data.get('content')
            except json.JSONDecodeError:
                messages.error(request, 'Invalid JSON')
                return HttpResponseRedirect(reverse('dashboard'))
        else:
            # Handle form data
            content = request.POST.get('content')
        
        if not content:
            messages.error(request, 'Content is required')
            return HttpResponseRedirect(reverse('dashboard'))
            
        #validate character limit
        if len(content) > self.TWITTER_CHAR_LIMIT:
            messages.error(
                request, 
                f'Content exceeds Twitter\'s {self.TWITTER_CHAR_LIMIT} character limit. '
                f'Current length: {len(content)}'
            )
            return HttpResponseRedirect(reverse('dashboard'))
        
        # Auth check
        user_id = request.session.get('user_id')
        if not user_id:
            messages.error(request, 'Authentication required')
            return HttpResponseRedirect(reverse('login'))
        
        from django.contrib.auth.models import User
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            messages.error(request, 'User not found')
            return HttpResponseRedirect(reverse('login'))
        
        try:
            user_profile = UserProfile.objects.get(user=user)
        except UserProfile.DoesNotExist:
            messages.error(request, 'User profile not found')
            return HttpResponseRedirect(reverse('dashboard'))
        
        try:
            token = OAuthToken.objects.get(
                user=user_profile,
                provider='twitter'
            )
        except OAuthToken.DoesNotExist:
            messages.error(request, 'Twitter not connected')
            return HttpResponseRedirect(reverse('dashboard'))
        
        # if token is expired and refresh if needed
        if token.expires_at and token.expires_at < timezone.now():
            if not token.refresh_token:
                messages.error(request, 'Token expired and no refresh token available')
                return HttpResponseRedirect(reverse('dashboard'))
            
            success = self._refresh_token(token)
            if not success:
                messages.error(request, 'Failed to refresh token')
                return HttpResponseRedirect(reverse('dashboard'))
        
        # Create post status record
        post_status = PostStatus.objects.create(
            user=user_profile,
            platform='twitter',
            content=content,
            status='pending',
            access_token=token.access_token
        )
        
        success, post_id, error = self._post_to_twitter(token.access_token, content)
        #update post status
        post_status.status = 'posted' if success else 'failed'
        post_status.post_id = post_id
        post_status.error_message = error
        post_status.save()
        
        if success:
            messages.success(request, 'Tweet posted successfully!')
        else:
            messages.error(request, f'Failed to post tweet: {error}')
            
        return HttpResponseRedirect(reverse('dashboard'))
        
    def _refresh_token(self, token):
        """
        Refresh an expired OAuth token
        """
        config = OAUTH_CONFIG['twitter']
        
        refresh_data = {
            'grant_type': 'refresh_token',
            'refresh_token': token.refresh_token,
            'client_id': config['client_id'],
        }
        
        if config.get('client_secret'):
            refresh_data['client_secret'] = config['client_secret']
        
        auth_string = f"{config['client_id']}:{config['client_secret']}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()

        headers = {
        'Authorization': f'Basic {encoded_auth}',
        'Content-Type': 'application/x-www-form-urlencoded'
        }       
        response = requests.post(config['token_url'], data=refresh_data, headers=headers)

        if response.status_code != 200:
            error_message = f"Token refresh failed: {response.status_code} - {response.text}"
            print(error_message)  # Debugging
            return False
        
        token_info = response.json()
        
        token.access_token = token_info.get('access_token')
        if token_info.get('refresh_token'):
            token.refresh_token = token_info['refresh_token']
        
        if token_info.get('expires_in'):
            token.expires_at = timezone.now() + timezone.timedelta(seconds=int(token_info['expires_in']))
        
        token.save()
        return True

    def _post_to_twitter(self, access_token, content):
        """
        Post a tweet using Twitter API v2
        """
        # Double-check length as a safeguard
        if len(content) > self.TWITTER_CHAR_LIMIT:
            return False, None, f"Content exceeds Twitter's {self.TWITTER_CHAR_LIMIT} character limit"
            
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'text': content
        }
        
        response = requests.post(
            'https://api.twitter.com/2/tweets',
            headers=headers,
            json=payload
        )
        
        if response.status_code == 201:
            response_data = response.json()
            return True, response_data.get('data', {}).get('id'), None
        else:
            error_message = f"Error {response.status_code}: {response.text}"
            return False, None, error_message
        
class TwitterLogoutView(View):
    """
    Disconnects Twitter from the user account by removing the OAuth token
    """
    def get(self, request):
        print("TwitterLogoutView accessed")

        # Manual authentication check
        user_id = request.user.id
        print(f"Session user_id: {user_id}")

        if not user_id:
            print("User not logged in. Redirecting to login.")
            return redirect('login')

        from django.contrib.auth.models import User
        try:
            user = User.objects.get(id=user_id)
            print(f"User found: {user}")
        except User.DoesNotExist:
            print("User does not exist. Redirecting to login.")
            return redirect('login')

        try:
            user_profile = UserProfile.objects.get(user=user)
            print(f"UserProfile found: {user_profile}")
        except UserProfile.DoesNotExist:
            print("UserProfile does not exist. Redirecting to login.")
            return redirect('login')

        # Delete Twitter OAuth tokens
        deleted_count, _ = OAuthToken.objects.filter(
            user=user_profile,
            provider='twitter'
        ).delete()
        print(f"Deleted {deleted_count} OAuth tokens for user {user_profile}")

        print("Redirecting to dashboard.")
        return redirect('dashboard')
