import os

import pandas as pd
from django.conf import settings
from django.db.models import Sum, Avg, F, Count, ExpressionWrapper, DecimalField
from django.http import FileResponse
from django.shortcuts import render

from . import utils
from .forms import UploadForm, DateFilterForm
from .models import Product


def dashboard(request):
    kpi=Product.objects.aggregate(
        products=Count('id'),
        total_qty=Sum('quantity'),
        avg_price=Avg('price'),
    )

    revenue_exr=ExpressionWrapper(F('price')*F('quantity'),
                                  output_field=DecimalField(max_digits=12,decimal_places=2))

    top_cats=(Product.objects
              .values("category")
              .annotate(revenue=Sum(revenue_exr),items=Count("id"))
              .order_by("-revenue")[:5]
              )

    return render(request,"products/dashboard.html",{"kpi":kpi,"top_cats":top_cats})

def product_upload(request):
    ctx={"form":UploadForm()}
    if request.method=="POST":
        form=UploadForm(request.POST,request.FILES)
        if form.is_valid():
            up=request.FILES["file"]
            sheet=form.cleaned_data.get("sheet_name") or None
            updir=os.path.join(settings.MEDIA_ROOT,"uploads")
            os.makedirs(updir,exist_ok=True)
            fpath=os.path.join(updir,up.name)
            with open(fpath,"wb+") as dest:
                for ch in up.chunks():
                    dest.write(ch)

            df=utils.read_any(fpath,sheet)
            df=utils.normalize_for_product(df)

            rows=df.to_dict("records")
            if len(rows)==1:
                r=rows[0]

                Product.objects.update_or_create(
                    sku=r["sku"],
                    defaults=dict(
                        name=r["name"],
                        price=r["price"],
                        quantity=int(r["quantity"]),
                        category=r.get("category") or "",
                        tx_date=r["tx_date"],
                    )
                )

            elif len(rows)>1:
                for r in rows:
                    Product.objects.update_or_create(
                        sku=r["sku"],
                        defaults=dict(
                            name=r["name"],
                            price=r["price"],
                            quantity=int(r["quantity"]),
                            category=r.get("category") or "",
                            tx_date=r["tx_date"],
                        )
                    )

            ctx["msg"]=f"Uploaded : {len(rows)} rows"

    return render(request,"products/upload.html",ctx)

def product_export(request):
    qs=Product.objects.all().order_by("tx_date","sku")
    data=qs.values('sku','name','category','price','quantity','tx_date')
    df=pd.DataFrame.from_records(data)
    path=utils.df_to_excel_response(df,"products_export.xlsx")
    return FileResponse(open(path,"rb"),as_attachment=True,filename=os.path.basename(path))

def product_list(request):
    form=DateFilterForm(request.GET or None)
    qs=Product.objects.all().order_by("-tx_date","-id")

    if form.is_valid():
        name=form.cleaned_data.get("name")
        min_count=form.cleaned_data.get("min_count")
        max_count=form.cleaned_data.get("max_count")

        if name:
            qs=qs.filter(name__icontains=name)
        if min_count is not None:
            qs=qs.filter(quantity__gte=min_count)
        if max_count is not None:
            qs=qs.filter(quantity__lte=max_count)

    return render(request,"products/product_list.html",{"qs":qs,"form":form})



def template_download(request):
    import csv
    from django.http import HttpResponse
    response=HttpResponse(content_type="text/csv")
    response["Content-Disposition"]='attachment; filename="products_export.csv"'
    writer=csv.writer(response)
    writer.writerow(["sku","name","category","price","quantity","tx_date"])
    qs=Product.objects.all().order_by("tx_date","sku")
    for p in qs:
        writer.writerow([p.sku, p.name, p.category, p.price, p.quantity, p.tx_date])
    return response