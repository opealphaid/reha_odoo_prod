from odoo import api, fields, models, _, tools
import requests
import json
from odoo.exceptions import UserError
import base64
import re

Languages = [
    ('af', 'Afrikaans'),
    ('sq', 'Albanian'),
    ('ar', 'Arabic'),
    ('az', 'Azerbaijani'),
    ('bn', 'Bengali'),
    ('bg', 'Bulgarian'),
    ('ca', 'Catalan'),
    ('zh_CN', 'Chinese (CHN)'),
    ('zh_HK', 'Chinese (HKG)'),
    ('zh_TW', 'Chinese (TAI)'),
    ('hr', 'Croatian'),
    ('cs', 'Czech'),
    ('da', 'Danish'),
    ('nl', 'Dutch'),
    ('en', 'English'),
    ('en_GB', 'English (UK)'),
    ('en_US', 'English (US)'),
    ('et', 'Estonian'),
    ('fil', 'Filipino'),
    ('fi', 'Finnish'),
    ('fr', 'French'),
    ('ka', 'Georgian'),
    ('de', 'German'),
    ('el', 'Greek'),
    ('gu', 'Gujarati'),
    ('ha', 'Hausa'),
    ('he', 'Hebrew'),
    ('hi', 'Hindi'),
    ('hu', 'Hungarian'),
    ('id', 'Indonesian'),
    ('ga', 'Irish'),
    ('it', 'Italian'),
    ('ja', 'Japanese'),
    ('kn', 'Kannada'),
    ('kk', 'Kazakh'),
    ('rw_RW', 'Kinyarwanda'),
    ('ko', 'Korean'),
    ('ky_KG', 'Kyrgyz (Kyrgyzstan)'),
    ('lo', 'Lao'),
    ('lv', 'Latvian'),
    ('lt', 'Lithuanian'),
    ('mk', 'Macedonian'),
    ('ms', 'Malay'),
    ('ml', 'Malayalam'),
    ('mr', 'Marathi'),
    ('nb', 'Norwegian'),
    ('fa', 'Persian'),
    ('pl', 'Polish'),
    ('pt_BR', 'Portuguese (BR)'),
    ('pt_PT', 'Portuguese (POR)'),
    ('pa', 'Punjabi'),
    ('ro', 'Romanian'),
    ('ru', 'Russian'),
    ('sr', 'Serbian'),
    ('sk', 'Slovak'),
    ('sl', 'Slovenian'),
    ('es', 'Spanish'),
    ('es_AR', 'Spanish (ARG)'),
    ('es_ES', 'Spanish (SPA)'),
    ('es_MX', 'Spanish (MEX)'),
    ('sw', 'Swahili'),
    ('sv', 'Swedish'),
    ('ta', 'Tamil'),
    ('te', 'Telugu'),
    ('th', 'Thai'),
    ('tr', 'Turkish'),
    ('uk', 'Ukrainian'),
    ('ur', 'Urdu'),
    ('uz', 'Uzbek'),
    ('vi', 'Vietnamese'),
    ('zu', 'Zulu')
]


class WATemplate(models.Model):
    _name = "wa.template"
    _inherit = ['mail.render.mixin']
    _description = 'Whatsapp Templates'

    def init(self):
        video_path = tools.misc.file_path('all_in_one_whatsapp_odoo_community/static/tus_meta_whatsapp_base/static/src/video/wa-demo-video.mp4')
        attachment = self.env['ir.attachment'].sudo().search([('name', '=', 'demo-wa-video')])
        if not attachment:
            attachment_value = {
                'name': 'demo-wa-video',
                'datas': base64.b64encode(open(video_path, 'rb').read()),
                'mimetype': 'video/mp4',
            }
            attachment = self.env['ir.attachment'].sudo().create(attachment_value)

        pdf_path = tools.misc.file_path('all_in_one_whatsapp_odoo_community/static/tus_meta_whatsapp_base/static/src/pdf/TestPDFfile.pdf')
        attachment = self.env['ir.attachment'].sudo().search([('name', '=', 'demo-wa-pdf')])
        if not attachment:
            attachment_value = {
                'name': 'demo-wa-pdf',
                'datas': base64.b64encode(open(pdf_path, 'rb').read()),
                'mimetype': 'application/pdf',
            }
            attachment = self.env['ir.attachment'].sudo().create(attachment_value)

        pdf_path = tools.misc.file_path('all_in_one_whatsapp_odoo_community/static/tus_meta_whatsapp_base/static/src/image/whatsapp_default_set.png')
        attachment = self.env['ir.attachment'].sudo().search([('name', '=', 'demo-wa-image')])
        if not attachment:
            attachment_value = {
                'name': 'demo-wa-image',
                'datas': base64.b64encode(open(pdf_path, 'rb').read()),
                'mimetype': 'image/png',
            }
            attachment = self.env['ir.attachment'].sudo().create(attachment_value)

    @api.model
    def default_get(self, fields):
        res = super(WATemplate, self).default_get(fields)
        if not fields or 'model_id' in fields and not res.get('model_id') and res.get('model'):
            res['model_id'] = self.env['ir.model']._get(res['model']).id
        return res

    def _get_current_user_provider(self):
        # Multi Companies and Multi Providers Code Here
        provider_id = self.env.user.provider_ids.filtered(lambda x: x.company_id == self.env.company)
        if provider_id:
            return fields.first(provider_id)
        return False

    name = fields.Char('Name', translate=True, required=True)
    provider_id = fields.Many2one('provider', 'Provider',
                                  default=_get_current_user_provider)  # default=lambda self: self.env.user.provider_id
    model_id = fields.Many2one(
        'ir.model', string='Applies to',
        help="The type of document this template can be used with", ondelete='cascade', )
    model = fields.Char('Related Document Model', related='model_id.model', index=True, store=True, readonly=True)
    body_html = fields.Html('Body', render_engine='qweb', translate=True, prefetch=True, sanitize=False)
    state = fields.Selection([
        ('draft', 'DRAFT'),
        ('imported', 'IMPORTED'),
        ('added', 'ADDED TEMPLATE'),
    ], string='State', default='draft')
    namespace = fields.Char('Namespace')
    category = fields.Selection([('marketing', 'MARKETING'),
                                 ('utility', 'UTILITY'),
                                 ('authentication', 'AUTHENTICATION')],
                                'Category', default='utility', required=True)
    # language = fields.Char("Language", default="en")
    lang = fields.Many2one("res.lang", "Language")
    language = fields.Selection(string="Language", selection=Languages, default='en')
    components_ids = fields.One2many('components', 'wa_template_id', 'Components')
    graph_message_template_id = fields.Char(string="Template UID")
    show_graph_message_template_id = fields.Boolean(compute='_compute_show_graph_message_template_id')
    template_status = fields.Char(string="Template Status", readonly=True)
    template_type = fields.Selection([('template', 'Template'),
                                      ('interactive', 'Interactive')], string="Template Type")

    @api.returns('self', lambda value: value.id)
    def copy(self, default=None):
        res = super(WATemplate, self).copy(default)
        res.template_status = False
        for component in self.components_ids:
            res_component = component.copy({'wa_template_id': res.id})
            for variable in component.variables_ids:
                variable.copy({'component_id': res_component.id})
        return res

    @api.onchange("components_ids")
    def onchange_body_html(self):
        for rec in self:
            if rec.components_ids:
                for component in rec.components_ids.filtered(lambda x: x.type == 'body'):
                    rec.body_html = tools.plaintext2html(component.text) if component.text else ''

    @api.onchange("name")
    def onchange_name(self):
        for rec in self:
            if rec.name and not re.match("^[A-Za-z0-9_]*$", rec.name):
                raise UserError(_("Template name contains letters, numbers and underscores."))

    @api.constrains('name')
    def _constrain_name(self):
        for rec in self:
            if rec.name and not re.match("^[A-Za-z0-9_]*$", rec.name):
                raise UserError(_("Template name contains letters, numbers and underscores."))

    @api.depends('provider_id')
    def _compute_show_graph_message_template_id(self):
        for message in self:
            message.show_graph_message_template_id = bool(message.provider_id.provider == 'graph_api')

    @api.depends('model')
    def _compute_render_model(self):
        for template in self:
            template.render_model = template.model

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            res = super(WATemplate, self).create(vals)
            res.name = res.name.lower()
            return res

    def _get_send_button_params(self, component, object_data, params):
        dynamic_index = {button: i for i, button in
                         enumerate(component.wa_button_ids)}
        wa_buttons = component.wa_button_ids.filtered(
            lambda button: button.button_type in ['copy_code', 'flow', 'CATALOG'] or button.url_type == 'dynamic')
        if wa_buttons:
            for button, variable in zip(wa_buttons, component.variables_ids):
                parameters = []
                button_dict = {
                    'type': "button",
                    'sub_type': button.button_type.upper(),
                    'index': dynamic_index.get(button)
                }
                if button.button_type == 'url' and button.url_type == 'dynamic':
                    parameters.append(self.env['whatsapp.history']._get_variable_params_dict(variable, object_data))
                elif button.button_type == 'copy_code':
                    parameters.append({
                        "type": "coupon_code",
                        "coupon_code": button.coupon_text,
                    })
                elif button.button_type == 'flow':
                    parameters.append({
                        "type": "action",
                        "action": {
                            "flow_token": button.flow_id,
                        }
                    })
                elif button.button_type == 'CATALOG':
                    parameters.append({
                        "type": "action",
                        "action": {
                            "thumbnail_product_retailer_id": button.product_retailer_id
                        }
                    })

                button_dict.update({"parameters": parameters})
                params.append(button_dict)
            return params

    def _get_carousel_button_params(self, carousel, object_data, carousel_component):
        dynamic_index = {button: i for i, button in
                         enumerate(carousel.wa_button_ids)}
        wa_buttons = carousel.wa_button_ids.filtered(
            lambda button: button.button_type in ['quick_reply', 'copy_code', 'flow', 'CATALOG'] or button.url_type == 'dynamic')
        if wa_buttons:
            for button, variable in zip(wa_buttons, carousel.variables_ids.filtered(lambda x: x.component_type == "button")):
                parameters = []
                button_dict = {
                    'type': "button",
                    'sub_type': button.button_type.upper(),
                    'index': dynamic_index.get(button)
                }
                if button.button_type == 'url' and button.url_type == 'dynamic':
                    parameters.append(self.env['whatsapp.history']._get_variable_params_dict(variable, object_data))
                elif button.button_type == 'quick_reply':
                    parameters.append({
                        "type": "PAYLOAD",
                        "payload": button.button_text
                    })
                elif button.button_type == 'copy_code':
                    parameters.append({
                        "type": "coupon_code",
                        "coupon_code": button.coupon_text,
                    })
                elif button.button_type == 'flow':
                    parameters.append({
                        "type": "action",
                        "action": {
                            "flow_token": button.flow_id,
                        }
                    })
                elif button.button_type == 'CATALOG':
                    parameters.append({
                        "type": "action",
                        "action": {
                            "thumbnail_product_retailer_id": button.product_retailer_id
                        }
                    })

                button_dict.update({"parameters": parameters})
                carousel_component.append(button_dict)
            return carousel_component

    def _get_carousel_params(self, component, object_data, provider, cards):
        carousel_index = {carousel: i for i, carousel in enumerate(component.wa_carousel_ids)}
        for carousel in component.wa_carousel_ids:
            carousel_component = []
            header_dict = {}
            if carousel.header_formate in ['image', 'video']:
                if carousel.attachment_ids:
                    for attachment in carousel.attachment_ids:
                        answer = provider.send_image(attachment)
                        if answer.status_code == 200:
                            dict = json.loads(answer.text)
                            header_dict.update({"type": "HEADER",
                                                "parameters": [{
                                                    "type": carousel.header_formate.upper(),
                                                    carousel.header_formate: {
                                                        "id": dict.get('id')}
                                                }]})
                carousel_component.append(header_dict)

            if carousel.carousel_body:
                body_dict = {}
                if carousel.variables_ids.filtered(lambda x: x.component_type == "body"):
                    body_dict.update({'type': "BODY"})
                    parameters = []
                    for variable in carousel.variables_ids.filtered(lambda x: x.component_type == "body"):
                        parameters.append(self.env['whatsapp.history']._get_variable_params_dict(variable, object_data))
                    body_dict.update({'parameters': parameters})
                    carousel_component.append(body_dict)
            if carousel.wa_button_ids:
                self._get_carousel_button_params(carousel, object_data, carousel_component)
            cards.append({"card_index": carousel_index.get(carousel),
                          "components": carousel_component})
        return cards

    def add_whatsapp_template(self):
        components = []
        for component in self.components_ids:
            dict = {}
            if component.type == 'header':
                if component.formate == 'media':
                    base_url = self.env.company.get_base_url()
                    domain = []
                    if component.media_type == 'document':
                        domain.append(('name', '=', 'demo-wa-pdf'))
                    if component.media_type == 'video':
                        domain.append(('name', '=', 'demo-wa-video'))
                    if component.media_type == 'image':
                        domain.append(('name', '=', 'demo-wa-image'))
                    attachment = self.env['ir.attachment'].sudo().search(domain)
                    if attachment:
                        answer = self.provider_id.graph_api_upload_demo_document(attachment)
                        if answer.status_code == 200:
                            data = json.loads(answer.text)
                            file_handle = data.get('h')
                            dict.update({"example": {
                                "header_handle": [file_handle]
                            }, 'type': component.type.upper(), 'format': component.media_type.upper(), })
                        components.append(dict)
                else:
                    header_text = []
                    for variable in component.variables_ids:
                        header_text.append('Test')
                    if header_text:
                        dict.update({"example": {
                            "header_text": header_text}})
                    if component.text:
                        dict.update({'text': component.text, 'type': component.type.upper(),
                                     'format': component.formate.upper()})
                        components.append(dict)

            elif component.type == 'buttons':
                dict.update({"type": component.type.upper()})
                button_list = []
                for button in component.wa_button_ids:
                    button_dict = {}
                    if button.button_type == 'phone':
                        button_dict.update({'type': 'PHONE_NUMBER', 'text': button.button_text, 'phone_number': button.phone_number})
                        button_list.append(button_dict)
                    elif button.button_type == 'url':
                        if button.url_type == 'static':
                            button_dict.update({'type': "URL", 'text': button.button_text,
                                                'url': button.static_website_url})

                            button_list.append(button_dict)
                        elif button.url_type == 'dynamic':
                            button_text = []
                            for variable in component.variables_ids:
                                button_text.append('Test')
                            button_dict.update({'type': "URL", 'text': button.button_text,
                                                'url': button.dynamic_website_url,
                                                "example": button_text,
                                                })
                            button_list.append(button_dict)
                    elif button.button_type in ['quick_reply', 'copy_code']:
                        button_dict.update({'type': button.button_type.upper(), 'text': button.button_text})
                        button_list.append(button_dict)
                dict.update({"buttons": button_list})
                components.append(dict)

            elif component.type == 'limited_time_offer':
                dict.update({'type': component.type.upper(), 'limited_time_offer': {'text': component.text,
                                                                                    'has_expiration': component.is_expiration}})
                components.append(dict)

            elif component.type == 'carousel' and component.wa_carousel_ids:
                cards = []
                for carousel in component.wa_carousel_ids:
                    carousel_components = []
                    attachment = self.env['ir.attachment']
                    if carousel.header_formate == 'image':
                        attachment = self.env['ir.attachment'].sudo().search([('name', '=', 'demo-wa-image')])
                    elif carousel.header_formate == 'video':
                        attachment = self.env['ir.attachment'].sudo().search([('name', '=', 'demo-wa-video')])

                    if attachment:
                        answer = self.provider_id.graph_api_upload_demo_document(attachment)
                        if answer.status_code == 200:
                            data = json.loads(answer.text)
                            file_handle = data.get('h')
                            header_dic = {
                                'type': "HEADER",
                                'format': carousel.header_formate.upper(),
                                "example": {"header_handle": [file_handle]}
                            }
                            carousel_components.append(header_dic)

                    body_text = []
                    for variable in carousel.variables_ids.filtered(lambda x: x.component_type == "body"):
                        body_text.append('Test')
                    body_dic = {}
                    if body_text:
                        body_dic.update({"example": {
                            "body_text": [body_text
                                          ]}})
                    if carousel.carousel_body:
                        body_dic.update({'text': carousel.carousel_body, 'type': "BODY"})
                        carousel_components.append(body_dic)

                    if carousel.wa_button_ids:
                        button_list = []
                        for button in carousel.wa_button_ids:
                            button_dict = {}
                            if button.button_type == 'phone':
                                button_dict = {
                                    'type': 'PHONE_NUMBER',
                                    'text': button.button_text,
                                    'phone_number': button.phone_number
                                }
                            elif button.button_type == 'url':
                                if button.url_type == 'static':
                                    button_dict = {
                                        'type': "URL",
                                        'text': button.button_text,
                                        'url': button.static_website_url
                                    }
                                elif button.url_type == 'dynamic':
                                    button_text = []
                                    for variable in carousel.variables_ids.filtered(lambda x: x.component_type == "button"):
                                        button_text.append('Test')
                                    button_dict = {
                                        'type': "URL",
                                        'text': button.button_text,
                                        'url': button.dynamic_website_url,
                                        "example": button_text
                                    }
                            elif button.button_type == 'quick_reply':
                                button_dict = {
                                    'type': button.button_type.upper(),
                                    'text': button.button_text
                                }
                            button_list.append(button_dict)
                        buttons_dict = {
                            "type": "BUTTONS",
                            "buttons": button_list
                        }
                        carousel_components.append(buttons_dict)

                    cards.append({'components': carousel_components})

                components.append({"type": "CAROUSEL", "cards": cards})

            else:
                body_text = []
                for variable in component.variables_ids:
                    body_text.append('Test')
                if body_text:
                    dict.update({"example": {
                        "body_text": [body_text
                                      ]}})
                if component.text:
                    dict.update({'text': component.text, 'type': component.type.upper(), })
                    components.append(dict)

        if components:
            answer = None
            if self._context.get('resubmit_template', False):
                answer = self.provider_id.resubmit_template(self.category.upper(), self.graph_message_template_id,
                                                            components)
            else:
                answer = self.provider_id.add_template(self.name, self.language, self.category.upper(), components)

                dict = json.loads(answer.text)
            if answer.status_code == 200:

                if self.provider_id.provider == 'chat_api':
                    if 'message' in dict:
                        raise UserError(
                            (dict.get('message')))
                    if 'error' in dict:
                        raise UserError(
                            (dict.get('error').get('message')))
                    else:
                        if 'status' in dict and dict.get('status') == 'submitted':
                            self.state = 'added'
                            self.namespace = dict.get('namespace')

                if self.provider_id.provider == 'graph_api':
                    if 'message' in dict:
                        raise UserError(
                            (dict.get('message')))
                    if 'error' in dict:
                        raise UserError(
                            (dict.get('error').get('message')))
                    else:
                        if 'id' in dict:
                            self.state = 'added'
                            self.graph_message_template_id = dict.get('id')
        else:
            raise UserError(
                ("please add components!"))

    def remove_whatsapp_template(self):
        answer = self.provider_id.remove_template(self.name)
        if answer.status_code == 200:
            dict = json.loads(answer.text)
            if dict.get('message', False):
                raise UserError(
                    (dict.get('message')))
            if dict.get('error', False):
                raise UserError(
                    (dict.get('error').get('message')))
            if dict.get('success', False):
                self.state = 'draft'

    def add_imported_whatsapp_template(self):
        self.write({'state': 'added'})

    def get_whatsapp_template_status(self):
        templates = self._context.get('single_template') and self.sudo() or self.sudo().search([])
        for rec in templates:
            if rec.provider_id.graph_api_authenticated:
                base_url = rec.provider_id.graph_api_url + rec.provider_id.graph_api_business_id + '/message_templates?name=' + rec.name + '&access_token=' + rec.provider_id.graph_api_token
                headers = {"Authorization": rec.provider_id.graph_api_token}
                try:
                    response = requests.get(base_url, headers=headers)
                    if response.status_code == 200:
                        response_data = response.json()
                        if response_data['data']:
                            for data in response_data['data']:
                                if rec.name == data['name']:
                                    rec.write({
                                        'template_status': data['status'],
                                        'graph_message_template_id': data['id'],
                                    })
                        else:
                            rec.write({
                                'template_status': False
                            })
                except requests.exceptions.ConnectionError:
                    raise UserError(
                        ("please check your internet connection."))

    def send_pre_message_by_whatsapp(self):
        partner_id = self.env.context.get('partner', False)
        if partner_id:
            wizard_rec = self.env['wa.compose.message'].with_context(active_model=self.model,
                                                                     active_id=partner_id).create(
                {'partner_id': partner_id, 'provider_id': self.provider_id.id,
                 'template_id': self.id})
            wizard_rec.onchange_template_id_wrapper()
            return wizard_rec.send_whatsapp_message()
