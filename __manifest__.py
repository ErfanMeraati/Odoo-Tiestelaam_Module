{
    'name': 'استعلام قیمت آنلاین',
    'version': '1.0',
    'category': 'فروش/محصولات',
    'summary': 'استعلام قیمت کالاها از سایت‌های مختلف',
    'author': 'Erfan Meraati',
    'website': 'meraati.net',
    'depends': ['sale', 'product'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/price_inquiry_views.xml',
        'data/price_inquiry_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tiestelaam/static/src/css/price_inquiry.css',
        ],
    },
    'installable': True,
    'application': True,
}
