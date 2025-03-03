from nextweb import secret

OAUTH_CONFIG = {
    "linkedin": {
        "client_id": secret.LINKEDIN_CLIENT_ID,
        "client_secret": secret.LINKEDIN_CLIENT_SECRET,
        "authorization_url": "https://www.linkedin.com/oauth/v2/authorization",
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "redirect_uri": secret.LINKEDIN_REDIRECT_URI,
        "callback_url": secret.LINKEDIN_REDIRECT_URI,
        "scopes": [
            "openid",               
            "profile",             
            "w_member_social",       
            "email",               
        ],
    },
    
    "twitter": {
        "client_id": secret.TWITTER_CLIENT_ID,
        "client_secret": secret.TWITTER_CLIENT_SECRET,
        "authorization_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "redirect_uri": secret.TWITTER_REDIRECT_URI,
        "callback_url": secret.TWITTER_REDIRECT_URI,
        "scopes": [
            "tweet.read",
            "tweet.write",
            "users.read",
            "offline.access",
        ],
    },
}
