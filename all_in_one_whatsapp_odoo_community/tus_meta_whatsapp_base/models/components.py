from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.all_in_one_whatsapp_odoo_community.tus_meta_whatsapp_base.models.whatsapp_history import image_type, video_type, audio_type, document_type
from datetime import datetime
import pytz
from odoo.tools import config


class Components(models.Model):
    _name = "components"
    _description = 'Whatsapp Components'

    sequence = fields.Integer(string="Sequence")
    type = fields.Selection([('header', 'HEADER'),
                             ('body', 'BODY'),
                             ('footer', 'FOOTER'), ('buttons', 'BUTTONS'),
                             ('interactive', 'INTERACTIVE'),
                             ('carousel', 'CAROUSEL'),
                             ('limited_time_offer', 'Limited Time Offer'), ('order_status', 'Order Status')],
                            'Type', default='header')
    formate = fields.Selection([('text', 'TEXT'),
                                ('media', 'MEDIA')],
                               'Formate', default='text')
    formate_media_type = fields.Selection([('static', 'Static Media File'),
                                           ('dynamic', 'Dynamic Media File')], string="Format Media Type",
                                          default='dynamic')

    media_type = fields.Selection([('document', 'DOCUMENT'),
                                   ('video', 'VIDEO'),
                                   ('image', 'IMAGE'), ],
                                  'Media Type', default='document')
    attachment_ids = fields.Many2many('ir.attachment', string="Attach Document")
    add_security_recommendation =fields.Boolean(string="Add Security recommendation",default=True,readonly=True)
    text = fields.Text('Text')

    variables_ids = fields.One2many('variables', 'component_id', 'Variables')
    wa_template_id = fields.Many2one('wa.template')
    model_id = fields.Many2one('ir.model', related="wa_template_id.model_id")
    code_expiration_minutes =fields.Integer(string="Code Expiration Minutes")
    wa_button_ids = fields.One2many('wa.button.component', 'components_id', string="Buttons")
    wa_carousel_ids = fields.One2many('wa.carousel.component', 'component_id', string="Carousel Components")
    footer_text = fields.Char(string="Footer Text", default="Not interested? Tap Stop promotions")
    interactive_type = fields.Selection([('button', 'BUTTON'),
                                         ('list', 'LIST'),
                                         ('product', 'PRODUCT'),
                                         ('product_list', 'PRODUCT LIST')],
                                        'Interactive Message Type', default='button')
    interactive_list_ids = fields.One2many(comodel_name="interactive.list.title", inverse_name="component_id",
                                           string="List Items")
    interactive_button_ids = fields.One2many(comodel_name="interactive.button", inverse_name="component_id",
                                             string="Button Items")
    interactive_product_list_ids = fields.One2many(comodel_name="interactive.product.list", inverse_name="component_id",
                                                   string="Product List Items")
    catalog_id = fields.Char(string="Catalog ID")
    product_retailer_id = fields.Char(string="Product Retailer ID")

    is_expiration = fields.Boolean(string='Is Expiration', default=True)
    limited_offer_exp_date = fields.Datetime(string='Offer Expiry Date', readonly=False)

    @api.onchange("text",'interactive_list_ids','interactive_button_ids')
    def onchange_text(self):
        for rec in self:
            if rec.type == 'header' and rec.formate == 'text' and rec.text and len(rec.text) > 60:
                raise UserError(_("60-character limit for headers text."))
            if rec.type == 'body' and rec.formate == 'text' and rec.text and len(rec.text) > 1024:
                raise UserError(_("1,024-character limit for body text."))
            # if rec.type == 'buttons' and len(rec.wa_button_ids) > 3:
            #     raise UserError(_("You Can Only Add 3 Buttons!!"))
            if rec.type == 'interactive' and rec.interactive_type == 'button' and len(rec.interactive_button_ids) > 3:
                raise UserError(_("You Can Only Add 3 Buttons!!"))
            if rec.type == 'interactive' and rec.interactive_type == 'list' and len(rec.interactive_list_ids) > 10:
                raise UserError(_("You Can Only Add 10 Lists!!"))

    @api.constrains('type', 'formate', 'text')
    def _constrain_text_length(self):
        for rec in self:
            if rec.type == 'header' and rec.formate == 'text' and rec.text and len(rec.text) > 60:
                raise UserError(_("60-character limit for headers text."))
            if rec.type == 'body' and rec.formate == 'text' and rec.text and len(rec.text) > 1024:
                raise UserError(_("1,024-character limit for body text."))

    @api.onchange('attachment_ids')
    def onchange_check_attachment(self):
        for rec in self:
            if rec.attachment_ids:
                for attachment_id in rec.attachment_ids:
                    if rec.formate_media_type == 'static' and rec.media_type == 'document':
                        if attachment_id.mimetype not in document_type:
                            raise ValidationError("Invalid type %s for document" % attachment_id.mimetype)
                    if rec.formate_media_type == 'static' and rec.media_type == 'video':
                        if attachment_id.mimetype not in video_type:
                            raise ValidationError("Invalid type %s for video" % attachment_id.mimetype)
                    if rec.formate_media_type == 'static' and rec.media_type == 'image':
                        if attachment_id.mimetype not in image_type:
                            raise ValidationError("Invalid type %s for image" % attachment_id.mimetype)
