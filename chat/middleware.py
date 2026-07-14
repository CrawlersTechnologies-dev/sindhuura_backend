from urllib.parse import parse_qs
from django.contrib.auth.models import AnonymousUser
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async


class JWTAuthMiddleware(BaseMiddleware):

    @database_sync_to_async
    def get_user(self, token):
        # ⬇️ IMPORT HERE (NOT at top)
        from rest_framework_simplejwt.authentication import JWTAuthentication

        jwt_auth = JWTAuthentication()
        validated_token = jwt_auth.get_validated_token(token)
        return jwt_auth.get_user(validated_token)

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        token_list = parse_qs(query_string).get("token")

        if token_list:
            try:
                scope["user"] = await self.get_user(token_list[0])
            except Exception:
                scope["user"] = AnonymousUser()
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)




