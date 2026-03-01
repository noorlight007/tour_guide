from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView

from core.choices import UserRole
from core.models import User
from core.permissions import IsSuperUser
from core.rest.serializers.users import UserSerializer


class UserListCreateApiView(ListCreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsSuperUser]

    def get_queryset(self):
        queryset = User.objects.filter(role=UserRole.ADMIN)
        queryset = list(queryset)
        queryset.append(self.request.user)
        return queryset


class UserDetailsApiVew(RetrieveUpdateDestroyAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsSuperUser]
    lookup_field = "id"

    def get_queryset(self):
        queryset = User.objects.filter(role=UserRole.ADMIN)
        queryset = list(queryset)
        queryset.append(self.request.user)
        return queryset
