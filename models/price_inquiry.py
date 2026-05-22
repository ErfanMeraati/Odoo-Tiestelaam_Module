from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
from bs4 import BeautifulSoup
import logging
import re
import json

_logger = logging.getLogger(__name__)


class PriceInquiryLine(models.Model):
    """خطوط محصولات مشابه"""
    _name = 'price.inquiry.line'
    _description = 'خطوط استعلام قیمت'
    _order = 'sequence asc'
    
    inquiry_id = fields.Many2one('price.inquiry', 'استعلام والد', required=True, ondelete='cascade')
    sequence = fields.Integer('ترتیب', default=0)
    name = fields.Char('نام محصول')
    price = fields.Float('قیمت')
    url = fields.Char('لینک')
    source = fields.Char('منبع')
    button_url = fields.Html('لینک محصول', compute='_compute_button_url', sanitize=False)

    def _compute_button_url(self):
        for rec in self:
            if rec.url:
                rec.button_url = f"""
                <a href="{rec.url}" target="_blank"
                style="
                background:#2563eb;
                color:white;
                padding:6px 14px;
                border-radius:8px;
                text-decoration:none;
                font-weight:600;
                ">
                🔎 باز کردن محصول
                </a>
                """
            else:
                rec.button_url = ""



class PriceInquiry(models.Model):
    _name = 'price.inquiry'
    _description = 'استعلام قیمت آنلاین'
    _order = 'create_date desc'

    name = fields.Char('نام کالا', required=True)
    product_id = fields.Many2one('product.product', 'محصول مرتبط')
    source = fields.Selection([
        ('torob', 'ترب'),
        ('digikala', 'دیجی‌کالا'),
    ], 'منبع', required=True, default='digikala')
    price = fields.Float('قیمت استعلام شده')
    url = fields.Char('لینک محصول')
    inquiry_date = fields.Datetime('تاریخ استعلام', default=fields.Datetime.now)
    state = fields.Selection([
        ('draft', 'در انتظار'),
        ('done', 'انجام شده'),
        ('failed', 'ناموفق'),
    ], default='draft', string='وضعیت')
    error_message = fields.Text('پیام خطا')
    
    line_ids = fields.One2many('price.inquiry.line', 'inquiry_id', 'محصولات مشابه')
    line_count = fields.Integer('تعداد محصولات مشابه', compute='_compute_line_count', store=True)

    user_id = fields.Many2one(
        'res.users',
        string='کاربر',
        default=lambda self: self.env.user,
        readonly=True
    )

    @api.depends('line_ids')
    def _compute_line_count(self):
        for record in self:
            record.line_count = len(record.line_ids)

    @api.onchange('source')
    def _onchange_source(self):
        for record in self:
            if record.state in ['done', 'failed']:
                record.state = 'draft'
                record.price = 0
                record.url = False
                record.error_message = False

    def action_inquiry_price(self):
        for record in self:
            try:
                record.line_ids.unlink()
                
                if record.source == 'torob':
                    result = self._get_torob_price(record.name)
                elif record.source == 'digikala':
                    result = self._get_digikala_price(record.name)
                else:
                    raise UserError('منبع پشتیبانی نشده')
                
                lines = []
                for idx, product in enumerate(result.get('products', [])):
                    lines.append((0, 0, {
                        'sequence': idx + 1,
                        'name': product.get('name', ''),
                        'price': product.get('price', 0),
                        'url': product.get('url', ''),
                        'source': record.source,
                    }))
                
                record.write({
                    'price': result.get('price', 0),
                    'url': result.get('url', ''),
                    'line_ids': lines,
                    'state': 'done',
                    'error_message': False,
                    'inquiry_date': fields.Datetime.now()
                })
                
            except Exception as e:
                _logger.error(f'خطا در استعلام قیمت: {str(e)}')
                record.write({
                    'state': 'failed',
                    'error_message': str(e)
                })

    def _convert_persian_arabic_numbers(self, text):
        if not text:
            return text
        
        conversion_map = {
            '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
            '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
            '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
            '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
        }
        
        result = text
        for old, new in conversion_map.items():
            result = result.replace(old, new)
        
        return result

    def _extract_price_from_text(self, text):
        if not text:
            return 0
        
        text = self._convert_persian_arabic_numbers(text)
        numbers = re.findall(r'[\d]+', text)
        
        if not numbers:
            return 0
        
        number_str = ''.join(numbers)
        
        try:
            return float(number_str)
        except:
            return 0

    def _get_torob_price(self, product_name):
        """دریافت قیمت از ترب"""
        _logger.info(f'شروع استعلام قیمت از ترب برای: {product_name}')
        
        search_url = f"https://torob.com/search/?query={product_name}&_search_landing=header"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'Accept-Language': 'fa-IR,fa;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        
        try:
            response = requests.get(search_url, headers=headers, timeout=20)
            _logger.info(f'کد پاسخ ترب: {response.status_code}')
            
            if response.status_code != 200:
                raise Exception(f'خطای HTTP: {response.status_code}')
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            products_list = []
            
            product_links = soup.find_all('a', href=re.compile(r'/p/[a-zA-Z0-9-]+/'))
            
            _logger.info(f'تعداد لینک‌های محصول یافت شده: {len(product_links)}')
            
            seen_urls = set()
            
            for link in product_links:
                try:
                    href = link.get('href', '')
                    
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    
                    url = 'https://torob.com' + href if href.startswith('/') else href
                    
                    name = ''
                    price = 0
                    
                    parent = link.parent
                    for level in range(20):
                        if not parent:
                            break
                        
                        if not name or len(name) < 5:
                            for tag in ['h2', 'h3', 'h4', 'span', 'div']:
                                name_elem = parent.find(tag, class_=re.compile(r'name|title', re.I))
                                if name_elem:
                                    name = name_elem.get_text(strip=True)
                                    break
                        
                        if price == 0:
                            price_elem = parent.find('div', class_=re.compile(r'price-text|price', re.I))
                            if price_elem:
                                price_text = price_elem.get_text(strip=True)
                                price = self._extract_price_from_text(price_text)
                        
                        if price == 0:
                            text = parent.get_text(strip=True)
                            price = self._extract_price_from_text(text)
                        
                        parent = parent.parent
                    
                    if not name or len(name) < 5:
                        name = link.get_text(strip=True)
                    
                    if name and len(name) > 3:
                        if price > 0:
                            products_list.append({
                                'name': name[:150],
                                'price': price,
                                'url': url,
                            })
                            _logger.info(f'محصول: {name[:50]} - {price} - {url}')
                        else:
                            products_list.append({
                                'name': name[:150],
                                'price': 0,
                                'url': url,
                            })
                    
                    if len(products_list) >= 20:
                        break
                        
                except Exception as e:
                    _logger.warning(f'خطا در پردازش لینک: {e}')
                    continue
            
            if len(products_list) < 5:
                _logger.info('روش 1 کافی نبود، تلاش با روش 2')
                products_list = self._get_torob_fallback(soup, search_url)
            
            if not products_list:
                raise Exception('محصولی در ترب یافت نشد')
            
            products_with_price = [p for p in products_list if p['price'] > 0]
            if products_with_price:
                products_list = products_with_price
            
            main_price = products_list[0].get('price', 0)
            main_url = products_list[0].get('url', '')
            
            _logger.info(f'تعداد نهایی محصولات: {len(products_list)}')
            
            return {
                'price': main_price,
                'url': main_url,
                'products': products_list
            }
            
        except Exception as e:
            _logger.error(f'خطا در ترب: {e}')
            raise Exception(f'خطا در دریافت قیمت از ترب: {str(e)}')

    def _get_torob_fallback(self, soup, search_url):
        """روش جایگزین برای ترب"""
        _logger.info('استفاده از روش جایگزین')
        
        products_list = []
        seen_urls = set()
        
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link.get('href', '')
            
            if '/p/' not in href:
                continue
            
            if href in seen_urls:
                continue
            seen_urls.add(href)
            
            url = 'https://torob.com' + href if href.startswith('/') else href
            
            name = ''
            price = 0
            
            parent = link
            for _ in range(20):
                parent = parent.parent
                if not parent:
                    break
                
                text = parent.get_text(strip=True)
                
                if price == 0:
                    price = self._extract_price_from_text(text)
                
                if not name or len(name) < 5:
                    for tag in ['h2', 'h3', 'h4']:
                        elem = parent.find(tag)
                        if elem:
                            name = elem.get_text(strip=True)
                            break
            
            if 50000 < price < 500000000 and name and len(name) > 3:
                products_list.append({
                    'name': name[:150],
                    'price': price,
                    'url': url
                })
                
                if len(products_list) >= 20:
                    break
        
        return products_list

    def _get_digikala_price(self, product_name):
        """دریافت قیمت از دیجی‌کالا"""
        _logger.info(f'شروع استعلام قیمت از دیجی‌کالا برای: {product_name}')
        
        search_url = "https://api.digikala.com/v1/search/"
        
        params = {
            'q': product_name,
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'fa-IR,fa;q=0.9,en;q=0.8',
        }
        
        try:
            response = requests.get(search_url, params=params, headers=headers, timeout=15)
            _logger.info(f'کد پاسخ دیجی‌کالا: {response.status_code}')
            
            if response.status_code != 200:
                raise Exception(f'خطای HTTP: {response.status_code}')
            
            data = response.json()
            
            products_list = []
            main_price = 0
            main_url = ''
            
            if data.get('status') == 200:
                products = data.get('data', {}).get('products', [])
                
                for idx, product in enumerate(products[:20]):
                    price = 0
                    if 'default_variant' in product:
                        variant = product['default_variant']
                        if 'price' in variant:
                            price = variant['price'].get('selling_price', 0)
                            price = price / 10
                    
                    product_id = product.get('id')
                    url = f"https://www.digikala.com/product/{product_id}/"
                    name = product.get('title_fa') or product.get('title', '')
                    
                    products_list.append({
                        'name': name,
                        'price': price,
                        'url': url,
                    })
                    
                    if idx == 0:
                        main_price = price
                        main_url = url
            
            if not products_list:
                raise Exception('محصولی یافت نشد')
            
            return {
                'price': main_price,
                'url': main_url,
                'products': products_list
            }
            
        except Exception as e:
            _logger.error(f'خطا در دیجی‌کالا: {e}')
            raise Exception(f'خطا در دریافت قیمت از دیجی‌کالا: {str(e)}')


    def action_view_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'محصولات مشابه',
            'res_model': 'price.inquiry.line',
            'view_mode': 'list,form',
            'domain': [('inquiry_id', '=', self.id)],
        }
        


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    last_inquiry_price = fields.Float('آخرین قیمت استعلام شده')
    last_inquiry_date = fields.Datetime('تاریخ آخرین استعلام')
