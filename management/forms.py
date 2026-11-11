from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_slug
from django.db.models import Q
from django.utils.text import slugify

from management.models import StockMovement
from store.models import Brand, Category, Product


class ProductForm(forms.Form):
    """Unified product creation/edit form synchronized with Product + Inventory fields."""

    name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'e.g. AMD Ryzen 5 7600X'}),
    )
    sku = forms.CharField(
        max_length=60,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Auto-generated if blank (must be unique)'}),
    )
    model_number = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Manufacturer MPN / Model Code'}),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.order_by('display_order', 'name'),
        widget=forms.Select(attrs={'class': 'cc-select'}),
    )
    brand = forms.ModelChoiceField(
        queryset=Brand.objects.order_by('name'),
        required=False,
        empty_label='-- Select Brand --',
        widget=forms.Select(attrs={'class': 'cc-select'}),
    )
    new_brand_name = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Optional: create new brand'}),
    )
    status = forms.ChoiceField(
        choices=Product.STATUS_CHOICES,
        initial=Product.STATUS_DRAFT,
        widget=forms.Select(attrs={'class': 'cc-select'}),
    )
    price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'cc-input', 'step': '0.01', 'min': '0'}),
    )
    cost_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'cc-input', 'step': '0.01', 'min': '0', 'placeholder': 'Optional internal cost'}),
    )
    price_change_reason = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Optional reason for price/cost update'}),
    )
    warranty_months = forms.IntegerField(
        min_value=0,
        initial=36,
        widget=forms.NumberInput(attrs={'class': 'cc-input', 'min': '0'}),
    )
    short_description = forms.CharField(
        max_length=320,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Short summary shown on catalog cards'}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'cc-textarea', 'rows': 4, 'placeholder': 'Full product overview & notes'}),
    )
    is_featured = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
    )
    digital = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
    )
    initial_quantity = forms.IntegerField(
        min_value=0,
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'cc-input', 'min': '0'}),
    )
    low_stock_threshold = forms.IntegerField(
        min_value=0,
        initial=3,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'cc-input', 'min': '0'}),
    )
    restock_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'cc-input', 'type': 'date'}),
    )

    def __init__(self, *args, current_category=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Category.objects.filter(is_active=True)
        if current_category is not None and getattr(current_category, 'pk', None):
            qs = Category.objects.filter(Q(is_active=True) | Q(pk=current_category.pk))
        self.fields['category'].queryset = qs.order_by('display_order', 'name')


CATEGORY_ICON_CHOICES = [
    ('bi-cpu', 'Processor / CPU Chip'),
    ('bi-motherboard', 'Motherboard / Circuit'),
    ('bi-memory', 'Memory / RAM Stick'),
    ('bi-gpu-card', 'Graphics Card / GPU'),
    ('bi-nvme', 'Storage / SSD & HDD'),
    ('bi-lightning-charge', 'Power Supply / PSU'),
    ('bi-pc', 'PC Cabinet / Case'),
    ('bi-fan', 'CPU Cooler / Fan'),
    ('bi-wind', 'Case Fan / Airflow'),
    ('bi-display', 'Monitor / Display'),
    ('bi-keyboard', 'Keyboard / Input'),
    ('bi-mouse', 'Mouse / Pointer'),
    ('bi-plug', 'Cables / Accessories'),
    ('bi-box-seam', 'General Hardware Box'),
]


class CategoryForm(forms.Form):
    """Form for creating and editing hardware product categories in the management portal."""

    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'e.g. Graphics Cards (GPU)'}),
    )
    slug = forms.CharField(
        max_length=140,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input cc-mono', 'placeholder': 'Auto-generated from name if blank'}),
    )
    component_slot = forms.ChoiceField(
        choices=Category.COMPONENT_SLOT_CHOICES,
        initial='other',
        widget=forms.Select(attrs={'class': 'cc-select'}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'cc-textarea', 'rows': 3, 'placeholder': 'Optional storefront category description'}),
    )
    icon_class = forms.ChoiceField(
        choices=CATEGORY_ICON_CHOICES,
        initial='bi-cpu',
        widget=forms.Select(attrs={'class': 'cc-select'}),
    )
    display_order = forms.IntegerField(
        min_value=0,
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'cc-input cc-mono', 'min': '0'}),
    )
    is_pc_component = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
    )
    show_in_nav = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
    )

    def __init__(self, *args, category_instance: Category | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.category_instance = category_instance
        # Preserve an existing custom icon class not present in default preset options
        if category_instance and category_instance.icon_class:
            existing_choices = dict(self.fields['icon_class'].choices)
            if category_instance.icon_class not in existing_choices:
                self.fields['icon_class'].choices = [
                    *self.fields['icon_class'].choices,
                    (category_instance.icon_class, f'Custom ({category_instance.icon_class})'),
                ]

    def clean_name(self):
        name = ' '.join((self.cleaned_data.get('name') or '').split())
        if len(name) < 2:
            raise ValidationError('Category name must be at least 2 characters.')
        qs = Category.objects.filter(name__iexact=name)
        if self.category_instance is not None:
            qs = qs.exclude(pk=self.category_instance.pk)
        if qs.exists():
            raise ValidationError(f'A category named "{name}" already exists.')
        return name

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get('name') or ''
        raw_slug = (cleaned.get('slug') or '').strip().lower()
        resolved_slug = raw_slug or slugify(name)

        if not resolved_slug:
            self.add_error('slug', 'Provide a valid URL slug using letters, numbers, underscores, or hyphens.')
            return cleaned

        try:
            validate_slug(resolved_slug)
        except ValidationError:
            self.add_error('slug', 'Slug may only contain letters, numbers, underscores, or hyphens.')
            return cleaned

        if len(resolved_slug) > 140:
            self.add_error('slug', 'Slug cannot exceed 140 characters.')
            return cleaned

        slug_qs = Category.objects.filter(slug__iexact=resolved_slug)
        if self.category_instance is not None:
            slug_qs = slug_qs.exclude(pk=self.category_instance.pk)
        if slug_qs.exists():
            self.add_error('slug', f'The slug "{resolved_slug}" is already used by another category.')
            return cleaned

        cleaned['slug'] = resolved_slug
        cleaned['display_order'] = cleaned.get('display_order') or 0
        return cleaned


class StockAdjustmentForm(forms.Form):
    """Form for atomic inventory quantity adjustments."""

    MODE_CHOICES = [
        ('add', 'Add Units (+)'),
        ('subtract', 'Subtract Units (-)'),
        ('set', 'Set Exact Quantity (=)'),
    ]
    REASON_CHOICES = [
        (StockMovement.REASON_RESTOCK, 'Restock / Purchase Order'),
        (StockMovement.REASON_CUSTOMER_RETURN, 'Customer Return'),
        (StockMovement.REASON_DAMAGED, 'Damaged / Write-off'),
        (StockMovement.REASON_MANUAL_CORRECTION, 'Manual Stock Correction'),
        (StockMovement.REASON_SUPPLIER_ADJUSTMENT, 'Supplier Adjustment'),
        (StockMovement.REASON_OTHER, 'Other'),
    ]

    adjustment_mode = forms.ChoiceField(choices=MODE_CHOICES)
    quantity_value = forms.IntegerField(min_value=0)
    reason = forms.ChoiceField(choices=REASON_CHOICES)
    notes = forms.CharField(max_length=500, required=False)
    expected_version_token = forms.CharField(max_length=40, required=False)


class CSVImportUploadForm(forms.Form):
    """Upload form for Step 1 of CSV bulk import."""

    csv_file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={'class': 'cc-input', 'accept': '.csv,text/csv'}),
    )

    def clean_csv_file(self):
        uploaded = self.cleaned_data.get('csv_file')
        if not uploaded:
            raise ValidationError('Choose a CSV file.')
        name = (uploaded.name or '').lower()
        if not name.endswith('.csv'):
            raise ValidationError('File must have a .csv extension.')
        return uploaded


class CreateManagerUserForm(forms.Form):
    """Owner-only form to provision a new Inventory Manager account."""

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'e.g. inv_alex'}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'cc-input', 'placeholder': 'alex@corecraftr.local'}),
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input'}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input'}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'cc-input', 'autocomplete': 'new-password'}),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'cc-input', 'autocomplete': 'new-password'}),
    )

    def clean(self):
        cleaned = super().clean()
        pwd = cleaned.get('password')
        confirm = cleaned.get('confirm_password')
        if pwd and confirm and pwd != confirm:
            raise ValidationError('Passwords do not match.')
        return cleaned
