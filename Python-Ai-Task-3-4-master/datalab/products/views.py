import os

import pandas as pd
from django.conf import settings
from django.db.models import Sum, Avg, F, Count, ExpressionWrapper, DecimalField
from django.db.models.functions import TruncMonth, ExtractQuarter
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

def stats_view(request):
    import plotly.graph_objects as go
    from plotly.offline import plot

    revenue_exr=ExpressionWrapper(F('price')*F('quantity'),output_field=DecimalField(max_digits=12,decimal_places=2))

    monthly=list(Product.objects
             .annotate(month=TruncMonth("tx_date"))
             .values("month")
             .annotate(revenue=Sum(revenue_exr),items=Count("id"))
             .order_by("month")
             )

    quarterly=list(Product.objects
               .annotate(q=ExtractQuarter("tx_date"))
               .values("q")
               .annotate(revenue=Sum(revenue_exr),avg_price=Avg('price'))
               .order_by("q")
               )

    by_cat=list(Product.objects
            .values("category")
            .annotate(mean_price=Avg('price'),total_qty=Sum('quantity'))
            .order_by("-total_qty"))

    top_sku=list(Product.objects
            .values("sku","name","category")
             .annotate(revenue=Sum(revenue_exr),qty=Sum("quantity"))
             .order_by("-revenue")[:10]
             )

    low_stock=list(Product.objects
               .filter(quantity__lte=5).order_by("quantity","name")[:10]
               )

    chart_monthly = plot(
        go.Figure(data=[
            go.Scatter(x=[str(r["month"])[:7] for r in monthly],
                       y=[float(r["revenue"] or 0) for r in monthly],
                       mode="lines+markers", name="Gəlir",
                       line=dict(color="#636EFA", width=3), marker=dict(size=8)),
            go.Bar(x=[str(r["month"])[:7] for r in monthly],
                   y=[r["items"] for r in monthly],
                   name="Sifariş sayı", yaxis="y2",
                   marker_color="#EF553B", opacity=0.5),
        ], layout=go.Layout(
            title="Aylıq Gəlir",
            yaxis=dict(title="Gəlir ($)"),
            yaxis2=dict(title="Sifariş sayı", overlaying="y", side="right"),
            legend=dict(x=0, y=1.1, orientation="h"), template="plotly_white",
        )), output_type="div", include_plotlyjs=True
    )

    chart_quarterly = plot(
        go.Figure(data=[
            go.Bar(x=[f"Q{r['q']}" for r in quarterly],
                   y=[float(r["revenue"] or 0) for r in quarterly],
                   name="Gəlir", marker_color="#00CC96"),
            go.Scatter(x=[f"Q{r['q']}" for r in quarterly],
                       y=[float(r["avg_price"] or 0) for r in quarterly],
                       name="Orta qiymət", mode="lines+markers",
                       yaxis="y2", line=dict(color="#AB63FA", width=2)),
        ], layout=go.Layout(
            title="Rüblük Gəlir",
            yaxis=dict(title="Gəlir ($)"),
            yaxis2=dict(title="Orta qiymət ($)", overlaying="y", side="right"),
            legend=dict(x=0, y=1.1, orientation="h"), template="plotly_white",
        )), output_type="div", include_plotlyjs=False
    )

    chart_by_cat = plot(
        go.Figure(data=[
            go.Pie(labels=[r["category"] or "Unknown" for r in by_cat],
                   values=[r["total_qty"] or 0 for r in by_cat],
                   hole=0.4, name="Stok payı"),
        ], layout=go.Layout(
            title="Kateqoriyaya görə Stok Payı", template="plotly_white",
        )), output_type="div", include_plotlyjs=False
    )

    chart_top_sku = plot(
        go.Figure(data=[
            go.Bar(y=[r["name"] for r in top_sku],
                   x=[float(r["revenue"] or 0) for r in top_sku],
                   orientation="h", marker_color="#FFA15A",
                   text=[f"${float(r['revenue'] or 0):,.0f}" for r in top_sku],
                   textposition="outside"),
        ], layout=go.Layout(
            title="TOP 10 Məhsul (Gəlirə görə)",
            xaxis=dict(title="Gəlir ($)"), yaxis=dict(autorange="reversed"),
            template="plotly_white", height=420,
        )), output_type="div", include_plotlyjs=False
    )

    chart_low_stock = plot(
        go.Figure(data=[
            go.Bar(x=[r.name for r in low_stock], y=[r.quantity for r in low_stock],
                   marker_color=["#EF553B" if r.quantity == 0 else "#FFA15A" for r in low_stock],
                   text=[r.quantity for r in low_stock], textposition="outside"),
        ], layout=go.Layout(
            title="Stok Azlığı (≤ 5 ədəd)",
            xaxis=dict(title="Məhsul"), yaxis=dict(title="Miqdar"),
            template="plotly_white",
        )), output_type="div", include_plotlyjs=False
    )

    return render(request,"products/stats.html",{
        "monthly":monthly, "quarterly":quarterly,
        "by_cat":by_cat, "top_sku":top_sku, "low_stock":low_stock,
        "chart_monthly":chart_monthly, "chart_quarterly":chart_quarterly,
        "chart_by_cat":chart_by_cat, "chart_top_sku":chart_top_sku,
        "chart_low_stock":chart_low_stock,
    })

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