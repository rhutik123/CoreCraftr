from decimal import Decimal
from django import forms
from pc_builder.models import PCBuild


PREFERRED_BRAND_CHOICES = [
    ('AMD', 'AMD'),
    ('Intel', 'Intel'),
    ('ASUS', 'ASUS'),
    ('MSI', 'MSI'),
    ('Gigabyte', 'Gigabyte'),
    ('Corsair', 'Corsair'),
    ('DeepCool', 'DeepCool'),
    ('Crucial', 'Crucial'),
    ('Western Digital', 'Western Digital'),
    ('Samsung', 'Samsung'),
]


class BeginnerPreferencesForm(forms.Form):
    budget = forms.DecimalField(
        min_value=Decimal('18000'),
        max_value=Decimal('500000'),
        initial=Decimal('65000'),
        widget=forms.NumberInput(attrs={'class': 'cc-input', 'step': '1000', 'min': '18000'}),
        help_text='Total target budget in INR (Rs.).',
    )
    primary_use = forms.ChoiceField(
        choices=PCBuild.PRIMARY_USE_CHOICES,
        initial='gaming',
        widget=forms.Select(attrs={'class': 'cc-select'}),
    )
    priority_preference = forms.ChoiceField(
        choices=PCBuild.PRIORITY_CHOICES,
        initial='balanced',
        widget=forms.Select(attrs={'class': 'cc-select'}),
    )
    upgradeability_preference = forms.ChoiceField(
        choices=PCBuild.UPGRADEABILITY_CHOICES,
        initial='moderate',
        widget=forms.Select(attrs={'class': 'cc-select'}),
    )
    preferred_brands = forms.MultipleChoiceField(
        choices=PREFERRED_BRAND_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    include_monitor = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
    )
    include_peripherals = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
    )
    preserve_existing = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
        help_text='Keep components already in your build and recommend compatible parts for remaining slots.',
    )


class SaveBuildForm(forms.Form):
    name = forms.CharField(
        max_length=160,
        required=True,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'e.g. My 1080p Gaming Rig'}),
    )
