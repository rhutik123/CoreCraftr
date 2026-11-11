from django import forms
from django.core.exceptions import ValidationError

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
