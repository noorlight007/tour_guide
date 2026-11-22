from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import User
from tour_plan.models import Image, TourPlan


class TourImageTests(APITestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.client.force_authenticate(
            User.objects.create_user(email="images@example.com", password="test-password")
        )
        self.tour = TourPlan.objects.create(
            title="Rome tour", description="A tour of Rome", price_adult="25.00"
        )

    def upload(self, filename, content):
        return SimpleUploadedFile(filename, content, content_type="image/jpeg")

    def test_upload_can_be_attached_to_a_tour_and_read_back(self):
        response = self.client.post(
            reverse("image-list-create"),
            {"file": self.upload("tour.jpg", b"tour picture")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        image = Image.objects.get(pk=response.data["id"])
        self.assertEqual(Path(image.file.path).read_bytes(), b"tour picture")

        response = self.client.patch(
            reverse("tour-plan-detail", args=[self.tour.pk]),
            {"image_ids": [image.pk]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["images"][0]["id"], image.pk)
        self.assertTrue(response.data["images"][0]["file"].endswith(image.file.url))
        self.assertEqual(list(self.tour.images.values_list("pk", flat=True)), [image.pk])

    def test_replacing_file_keeps_the_tour_image_association(self):
        image = Image.objects.create(file=self.upload("original.jpg", b"original"))
        self.tour.images.add(image)

        response = self.client.patch(
            reverse("image-details", args=[image.pk]),
            {"file": self.upload("replacement.jpg", b"replacement")},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        image.refresh_from_db()
        self.assertEqual(Path(image.file.path).read_bytes(), b"replacement")
        self.assertEqual(list(self.tour.images.values_list("pk", flat=True)), [image.pk])

    def test_failed_replacement_preserves_the_original_image(self):
        image = Image.objects.create(file=self.upload("original.jpg", b"original"))
        original_name = image.file.name
        self.tour.images.add(image)

        with patch.object(image.file.storage, "save", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                with transaction.atomic():
                    self.client.patch(
                        reverse("image-details", args=[image.pk]),
                        {"file": self.upload("replacement.jpg", b"replacement")},
                        format="multipart",
                    )

        image.refresh_from_db()
        self.assertEqual(image.file.name, original_name)
        self.assertEqual(Path(image.file.path).read_bytes(), b"original")
        self.assertEqual(list(self.tour.images.values_list("pk", flat=True)), [image.pk])
