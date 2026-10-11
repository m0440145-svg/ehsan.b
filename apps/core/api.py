import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("apps.api")


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


def exception_handler(exc, context):
    """معالج أخطاء موحد يحوّل أخطاء طبقة الخدمات إلى استجابات JSON عربية."""
    if isinstance(exc, DjangoValidationError):
        messages = exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages}
        return Response({"errors": messages}, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, DjangoPermissionDenied):
        return Response({"detail": str(exc) or "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("خطأ غير متوقع في API")
        return Response({"detail": "حدث خطأ غير متوقع"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return response
