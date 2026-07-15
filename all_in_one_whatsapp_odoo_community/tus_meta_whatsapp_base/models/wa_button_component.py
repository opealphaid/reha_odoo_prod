from odoo import models, fields, api


class WaButtonComponent(models.Model):
    _name = 'wa.button.component'
    _description = "Whatsapp buttons components to send quick reply and call to action buttons"

    button_type = fields.Selection([('url', 'Url'),
                                    ('quick_reply', 'Quick Reply'),
                                    ('phone', 'Phone Number'),
                                    ('copy_code','Coupon Code')],
                                   'Button Type')
    button_text = fields.Char(string="Button Text", size=25)
    coupon_text=fields.Char(string="Coupon Text")
    url_type = fields.Selection([('static', 'Static'),
                                 ('dynamic', 'Dynamic')], 'URL Type')
    static_website_url = fields.Char(string="Website URL")
    dynamic_website_url = fields.Char(string='Dynamic URL')
    phone_number = fields.Char(string="Phone Number", size=20)
    components_id = fields.Many2one('components')
    carousel_id = fields.Many2one('wa.carousel.component')
