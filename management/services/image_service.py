import uuid
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from management.services.audit_service import log_portal_action
from store.models import ProductImage

ALLOWED_PIL_FORMATS = {
    'JPEG': 'jpg',
    'PNG': 'png',
    'WEBP': 'webp',
}


def validate_uploaded_image(uploaded_file) -> tuple[bytes, str]:
    """
    Strictly validate an uploaded file using Pillow binary verification.
    Returns (raw_bytes, safe_extension) or raises ValidationError.
    Rejects non-image payloads, SVG/HTML files, corrupted data, and oversized uploads.
    """
    if not uploaded_file:
        raise ValidationError('No image file was provided.')

    max_bytes = getattr(settings, 'PRODUCT_IMAGE_MAX_BYTES', 5 * 1024 * 1024)
    if getattr(uploaded_file, 'size', 0) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise ValidationError(f'Image exceeds the maximum allowed size of {max_mb} MB.')

    uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    if not raw_bytes:
        raise ValidationError('Uploaded image file is empty.')
    if len(raw_bytes) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise ValidationError(f'Image exceeds the maximum allowed size of {max_mb} MB.')

    try:
        with Image.open(BytesIO(raw_bytes)) as img:
            fmt = (img.format or '').upper()
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ValidationError('Invalid or corrupted image file. Only JPEG, PNG, and WEBP images are allowed.') from exc

    if fmt not in ALLOWED_PIL_FORMATS:
        raise ValidationError(f'Unsupported image format "{fmt or "unknown"}". Only JPEG, PNG, and WEBP are allowed.')

    return raw_bytes, ALLOWED_PIL_FORMATS[fmt]


def _build_safe_image_file(raw_bytes: bytes, ext: str) -> SimpleUploadedFile:
    content_types = {
        'jpg': 'image/jpeg',
        'png': 'image/png',
        'webp': 'image/webp',
    }
    safe_name = f'{uuid.uuid4().hex}.{ext}'
    return SimpleUploadedFile(safe_name, raw_bytes, content_type=content_types[ext])


@transaction.atomic
def add_product_images(product, files, *, make_first_primary: bool = False, actor=None, request=None) -> list:
    """Validate and store multiple gallery images on a product."""
    if not files:
        return []

    existing_qs = ProductImage.objects.filter(product=product)
    has_primary = existing_qs.filter(is_primary=True).exists()
    next_order = (existing_qs.order_by('-display_order').values_list('display_order', flat=True).first() or 0) + 1

    created = []
    for idx, uploaded in enumerate(files):
        raw_bytes, ext = validate_uploaded_image(uploaded)
        safe_file = _build_safe_image_file(raw_bytes, ext)
        is_primary = bool((make_first_primary and idx == 0) or (not has_primary and idx == 0))
        if is_primary:
            ProductImage.objects.filter(product=product, is_primary=True).update(is_primary=False)
            has_primary = True
        img_obj = ProductImage.objects.create(
            product=product,
            image=safe_file,
            alt_text=product.name[:200],
            is_primary=is_primary,
            display_order=next_order + idx,
        )
        created.append(img_obj)

    log_portal_action(
        actor=actor,
        action='product.images_uploaded',
        target_type='product',
        target_id=product.id,
        target_label=f'{product.sku} - {product.name}',
        after_data={'uploaded_image_ids': [i.id for i in created], 'count': len(created)},
        summary=f'Uploaded {len(created)} image(s) to product {product.sku}.',
        request=request,
    )
    return created


@transaction.atomic
def set_primary_product_image(product, image_id: int, *, actor=None, request=None) -> ProductImage:
    """Mark an existing gallery image as the product's primary image."""
    target = ProductImage.objects.filter(product=product, pk=image_id).first()
    if not target:
        raise ValidationError('Selected gallery image does not belong to this product.')

    ProductImage.objects.filter(product=product, is_primary=True).exclude(pk=target.pk).update(is_primary=False)
    if not target.is_primary:
        target.is_primary = True
        target.save(update_fields=['is_primary'])

    log_portal_action(
        actor=actor,
        action='product.image_set_primary',
        target_type='product',
        target_id=product.id,
        target_label=f'{product.sku} - {product.name}',
        after_data={'primary_image_id': target.id},
        summary=f'Set image #{target.id} as primary for {product.sku}.',
        request=request,
    )
    return target


@transaction.atomic
def replace_product_image(product, image_id: int, uploaded_file, *, actor=None, request=None) -> ProductImage:
    """Replace an existing gallery image after validating the replacement binary."""
    target = ProductImage.objects.filter(product=product, pk=image_id).first()
    if not target:
        raise ValidationError('Target image does not belong to this product.')

    raw_bytes, ext = validate_uploaded_image(uploaded_file)
    old_name = target.image.name if target.image else target.static_path
    target.image = _build_safe_image_file(raw_bytes, ext)
    target.static_path = ''
    target.save(update_fields=['image', 'static_path'])

    log_portal_action(
        actor=actor,
        action='product.image_replaced',
        target_type='product',
        target_id=product.id,
        target_label=f'{product.sku} - {product.name}',
        before_data={'image_id': target.id, 'previous_file': old_name},
        after_data={'image_id': target.id, 'new_file': target.image.name},
        summary=f'Replaced image #{target.id} on product {product.sku}.',
        request=request,
    )
    return target


@transaction.atomic
def delete_product_image(product, image_id: int, *, actor=None, request=None):
    """Safely remove a gallery image and promote another primary image if needed."""
    target = ProductImage.objects.filter(product=product, pk=image_id).first()
    if not target:
        raise ValidationError('Gallery image does not belong to this product.')

    was_primary = target.is_primary
    removed_id = target.id
    if target.image and target.image.name:
        target.image.delete(save=False)
    target.delete()

    if was_primary:
        next_img = ProductImage.objects.filter(product=product).order_by('display_order', 'id').first()
        if next_img:
            next_img.is_primary = True
            next_img.save(update_fields=['is_primary'])

    log_portal_action(
        actor=actor,
        action='product.image_deleted',
        target_type='product',
        target_id=product.id,
        target_label=f'{product.sku} - {product.name}',
        before_data={'deleted_image_id': removed_id, 'was_primary': was_primary},
        summary=f'Deleted image #{removed_id} from product {product.sku}.',
        request=request,
    )
