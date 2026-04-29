"""圖片處理 API。"""

from django.http import HttpResponse
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from .serializers import ProcessImageSerializer
from .services import ImageProcessingService


class ProcessImageView(APIView):
    """執行獨立圖片處理。"""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        serializer = ProcessImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        png_bytes = ImageProcessingService.process(
            user=request.user, data=serializer.validated_data
        )
        return HttpResponse(png_bytes, content_type="image/png")
