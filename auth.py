import os
import logging
from functools import wraps
import json
from jose import jwt
from flask import request, g
from urllib.request import urlopen
from dotenv import load_dotenv
load_dotenv()  # Add this before accessing environment variables

# Load environment variables
AUTH0_DOMAIN = os.getenv('AUTH0_DOMAIN')
AUTH0_CLIENT_ID = os.getenv('AUTH0_CLIENT_ID')
AUTH0_CLIENT_SECRET = os.getenv('AUTH0_CLIENT_SECRET')
AUTH0_AUDIENCE = os.getenv('AUTH0_AUDIENCE')
ALGORITHMS = ["RS256"]

# Print environment variables for debugging
print("Environment variables:")
print(f"AUTH0_DOMAIN: {AUTH0_DOMAIN}")
print(f"AUTH0_CLIENT_ID: {AUTH0_CLIENT_ID}")
print(f"AUTH0_CLIENT_SECRET: {AUTH0_CLIENT_SECRET}")
print(f"AUTH0_AUDIENCE: {AUTH0_AUDIENCE}")

class AuthError(Exception):
    def __init__(self, error, status_code):
        self.error = error
        self.status_code = status_code

# Validate required env vars
if not all([AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET, AUTH0_AUDIENCE]):
    raise ValueError("Missing required Auth0 environment variables")

def get_token_auth_header():
    auth = request.headers.get("Authorization", None)
    logging.info(f"Auth header received: {auth}")
    
    if not auth:
        raise AuthError({"code": "authorization_header_missing",
                        "description": "Authorization header is required"}, 401)

    parts = auth.split()
    if parts[0].lower() != "bearer":
        raise AuthError({"code": "invalid_header",
                        "description": "Authorization header must start with Bearer"}, 401)
    elif len(parts) == 1:
        raise AuthError({"code": "invalid_header",
                        "description": "Token not found"}, 401)
    elif len(parts) > 2:
        raise AuthError({"code": "invalid_header",
                        "description": "Authorization header must be Bearer token"}, 401)

    token = parts[1]
    logging.info(f"Token extracted successfully")
    return token

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'OPTIONS':  # Handle OPTIONS requests
            return '', 200  # Return a 200 response for preflight requests
        try:
            token = get_token_auth_header()
            
            # Get JWKS
            jwks_url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
            logging.info(f"Fetching JWKS")
            jsonurl = urlopen(jwks_url)
            jwks = json.loads(jsonurl.read())
            
            # Get token header
            unverified_header = jwt.get_unverified_header(token)
            logging.info(f"Token header verified")
            
            # Find matching key
            rsa_key = {}
            for key in jwks["keys"]:
                if key["kid"] == unverified_header["kid"]:
                    rsa_key = {
                        "kty": key["kty"],
                        "kid": key["kid"],
                        "use": key["use"],
                        "n": key["n"],
                        "e": key["e"]
                    }
                    break

            if not rsa_key:
                raise AuthError({"code": "invalid_header",
                               "description": "Unable to find appropriate key"}, 401)

            # Validate token
            try:
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=ALGORITHMS,
                    audience=AUTH0_AUDIENCE,
                    issuer=f"https://{AUTH0_DOMAIN}/",
                    options={
                        'verify_at_hash': False
                    }
                )
                logging.info("Token decoded successfully")
                
            except jwt.ExpiredSignatureError as e:
                logging.error(f"Token expired: {e}")
                raise AuthError({"code": "token_expired",
                               "description": "Token is expired"}, 401)
            except jwt.JWTClaimsError as e:
                logging.error(f"Invalid claims: {e}")
                raise AuthError({"code": "invalid_claims",
                               "description": f"Invalid claims: {e}"}, 401)
            except Exception as e:
                logging.error(f"Token validation error: {e}")
                raise AuthError({"code": "invalid_header",
                               "description": f"Token validation failed: {e}"}, 401)

            g.current_user = payload
            return f(*args, **kwargs)
            
        except Exception as e:
            logging.error(f"Auth error: {e}")
            raise
            
    return decorated