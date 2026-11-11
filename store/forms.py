from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from store.models import Customer, Order


class CreateUserForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'cc-input', 'placeholder': 'Email address'}),
    )
    first_name = forms.CharField(
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Full name (optional)'}),
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'cc-input', 'placeholder': 'Username'})
        self.fields['password1'].widget.attrs.update({'class': 'cc-input', 'placeholder': 'Password'})
        self.fields['password2'].widget.attrs.update({'class': 'cc-input', 'placeholder': 'Confirm password'})

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email address already exists.')
        return email


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            'name',
            'email',
            'phone',
            'default_address',
            'default_city',
            'default_state',
            'default_zipcode',
            'default_country',
            'preferred_builder_mode',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'cc-input'}),
            'email': forms.EmailInput(attrs={'class': 'cc-input'}),
            'phone': forms.TextInput(attrs={'class': 'cc-input'}),
            'default_address': forms.TextInput(attrs={'class': 'cc-input'}),
            'default_city': forms.TextInput(attrs={'class': 'cc-input'}),
            'default_state': forms.TextInput(attrs={'class': 'cc-input'}),
            'default_zipcode': forms.TextInput(attrs={'class': 'cc-input'}),
            'default_country': forms.TextInput(attrs={'class': 'cc-input'}),
            'preferred_builder_mode': forms.Select(attrs={'class': 'cc-select'}),
        }


class CheckoutForm(forms.Form):
    customer_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Full Name'}),
    )
    customer_email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'cc-input', 'placeholder': 'Email Address'}),
    )
    customer_phone = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Phone Number'}),
    )
    address = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Street Address / Flat / Landmark'}),
    )
    city = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'City'}),
    )
    state = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'State'}),
    )
    zipcode = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'PIN / ZIP Code'}),
    )
    country = forms.CharField(
        max_length=100,
        required=False,
        initial='India',
        widget=forms.TextInput(attrs={'class': 'cc-input', 'placeholder': 'Country'}),
    )
    payment_method = forms.ChoiceField(
        choices=Order.PAYMENT_METHOD_CHOICES,
        initial='cod_demo',
        widget=forms.RadioSelect(attrs={'class': 'cc-checkbox'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'cc-textarea', 'rows': 2, 'placeholder': 'Delivery or build notes (optional)'}),
    )
    acknowledge_incompatibility = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'cc-checkbox'}),
        label='I understand that some selected components may not work together.',
    )
