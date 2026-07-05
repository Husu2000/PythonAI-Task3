from django import forms

class UploadForm(forms.Form):
    file=forms.FileField(help_text="Excel/CSV (xlsx,xls,csv)")
    sheet_name=forms.CharField(required=False)

class DateFilterForm(forms.Form):
    name=forms.CharField(required=False, label="Product Name")
    min_count=forms.IntegerField(required=False, min_value=0, label="Min Count")
    max_count=forms.IntegerField(required=False, min_value=0, label="Max Count")