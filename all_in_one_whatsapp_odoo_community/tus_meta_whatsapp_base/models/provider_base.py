import requests
from odoo import _, api, fields, models, tools

from odoo.exceptions import UserError
import json

import base64

import base64


class Provider(models.Model):
    _name = 'provider'
    _description = 'Add Provider to configure the whatsapp'

    name = fields.Char('Name', required=True)
    provider = fields.Selection(string='Provider', required=True, selection=[('none', "No Provider Set")],
                                default='none')
    state = fields.Selection(
        string="State",
        selection=[('disabled', "Disabled"), ('enabled', "Enabled")],
        default='enabled', required=True, copy=False)
    company_id = fields.Many2one(  # Indexed to speed-up ORM searches (from ir_rule or others)
        string="Company", comodel_name='res.company', default=lambda self: self.env.company.id,
        required=True)
    user_ids = fields.Many2many('res.users', string='Operators')
    about = fields.Text("About")
    business_address = fields.Text("Address")
    business_description = fields.Text("Description")
    business_email = fields.Char("Email")
    business_profile_picture = fields.Image("Profile Picture", attachment=True, copy=False)
    business_website = fields.Char("Website")
    business_vertical = fields.Char("Vertical")

    verified_name = fields.Char("Verified Name")
    code_verification_status = fields.Char("Code Verification Status")
    display_phone_number = fields.Char("Display Phone Number")
    quality_rating = fields.Char("Quality Rating")
    platform_type = fields.Char("Platform Type")
    throughput_level = fields.Char("Throughput Level")
    webhook_configuration = fields.Char("Webhook Configuration")

    # phone change to mobile
    def direct_send_message(self, mobile, message):
        t = type(self)
        fn = getattr(t, f'{self.provider}_direct_send_message', None)
        res = fn(self, mobile, message, )
        return res

    def direct_send_file(self, mobile, attachment_id):
        t = type(self)
        fn = getattr(t, f'{self.provider}_direct_send_file', None)
        res = fn(self, mobile, attachment_id)
        return res

    def send_message(self, recipient, message, quotedMsgId=False):
        t = type(self)
        if self.provider != 'none':
            fn = getattr(t, f'{self.provider}_send_message', None)
            # eval_context = self._get_eval_context(self)
            # active_id = self._context.get('active_id')
            # run_self = self.with_context(active_ids=[active_id], active_id=active_id)
            res = fn(self, recipient, message, quotedMsgId)
            return res
        else:
            raise UserError(_("No Provider Set, Please Enable Provider"))

    def send_file(self, recipient, attachment_id):
        t = type(self)
        fn = getattr(t, f'{self.provider}_send_file', None)
        res = fn(self, recipient, attachment_id)
        return res

    def check_phone(self, mobile):
        t = type(self)
        fn = getattr(t, f'{self.provider}_check_phone', None)
        res = fn(self, mobile)
        return res

    def add_template(self, name, language, category, components):
        t = type(self)
        fn = getattr(t, f'{self.provider}_add_template', None)
        res = fn(self, name, language, category, components)
        return res

    def resubmit_template(self, category, template_id, components):
        t = type(self)
        fn = getattr(t, f'{self.provider}_resubmit_template', None)
        res = fn(self, category, template_id, components)
        return res

    def remove_template(self, name):
        t = type(self)
        fn = getattr(t, f'{self.provider}_remove_template', None)
        res = fn(self, name)
        return res

    def direct_send_template(self, template, language, namespace, mobile, params):
        t = type(self)
        fn = getattr(t, f'{self.provider}_direct_send_template', None)
        res = fn(self, template, language, namespace, mobile, params)
        return res

    def send_template(self, template, language, namespace, partner, params):
        t = type(self)
        fn = getattr(t, f'{self.provider}_send_template', None)
        res = fn(self, template, language, namespace, partner, params)
        return res

    def get_whatsapp_template(self):
        t = type(self)
        fn = getattr(t, f'{self.provider}_get_whatsapp_template', None)
        res = fn(self)
        return res

    def send_mpm_template(self, template, language, namespace, partner, params):
        t = type(self)
        fn = getattr(t, f'{self.provider}_send_mpm_template', None)
        res = fn(self, template, language, namespace, partner, params)
        return res

    def direct_send_mpm_template(self, template, language, namespace, mobile, params):
        t = type(self)
        fn = getattr(t, f'{self.provider}_direct_send_mpm_template', None)
        res = fn(self, template, language, namespace, mobile, params)
        return res

    def graph_api_direct_send_mpm_template(self, template, language, namespace, partner, params):
        if self.graph_api_authenticated:
            url = self.graph_api_url + self.graph_api_instance_id + "/messages"
            header_text = False
            header = {}
            wa_template_id = self.env['wa.template'].search(
                [('name', '=', template), ('template_type', '=', 'interactive')], limit=1) or self.env.context.get(
                'wa_template')
            # context_wa_template_id = self.env.context.get('wa_template')

            if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'header'):
                if any(i.get('type') == 'header' for i in params if 'type' in i):
                    if [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get('type') == 'text':
                        header_text = [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get(
                            'text')
                        header.update({"type": "text",
                                       "text": header_text})
                    if [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get(
                            'type') == 'document':
                        header_document = [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get(
                            'document')
                        header.update({"type": "document",
                                       "document": header_document})
                    if [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get(
                            'type') == 'image':
                        header_image = [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get(
                            'image')
                        header.update({"type": "image",
                                       "image": header_image})
                    if [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get(
                            'type') == 'video':
                        header_video = [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get(
                            'video')
                        header.update({"type": "video",
                                       "video": header_video})

                    temp = False
                    for i in params:
                        if 'type' in i and i.get('type') == 'header':
                            temp = i
                    if temp:
                        params.remove(temp)

                else:
                    if wa_template_id and wa_template_id.components_ids.filtered(
                            lambda x: x.type == 'header').formate == 'text':
                        header_text = wa_template_id.components_ids.filtered(
                            lambda x: x.type == 'header').text
                        header.update({"type": "text",
                                       "text": header_text})
                    else:
                        for component in wa_template_id.components_ids:
                            if component.formate == 'media':
                                if component.formate_media_type == 'static':
                                    IrConfigParam = self.env[
                                        "ir.config_parameter"
                                    ].sudo()
                                    base_url = IrConfigParam.get_param(
                                        "web.base.url", False
                                    )
                                    attachment_ids = component.attachment_ids
                                    if component.media_type == 'document':
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "document": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                    "filename": self.env[
                                                        "ir.attachment"
                                                    ]
                                                    .sudo()
                                                    .browse(
                                                        attachment_ids.ids[
                                                            0
                                                        ]
                                                    )
                                                    .name,
                                                },
                                            })
                                    if component.media_type == "video":
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "video": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                },
                                            })
                                    if component.media_type == "image":
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "image": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                },
                                            })
            body_text = False
            body = {}
            if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'body'):
                if any(i.get('type') == 'body' for i in params if 'type' in i):
                    if [i for i in params if i.get('type') == 'body'][0].get('parameters')[0].get('type') == 'text':
                        body_text = [i for i in params if i.get('type') == 'body'][0].get('parameters')[0].get('text')
                        body.update({"type": "text",
                                     "text": body_text})

                    temp = False
                    for i in params:
                        if 'type' in i and i.get('type') == 'body':
                            temp = i
                    if temp:
                        params.remove(temp)
                else:
                    if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'body'):
                        body_text = wa_template_id.components_ids.filtered(
                            lambda x: x.type == 'body').text
                        body.update({"text": body_text})

            footer_text = False
            footer = {}
            if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'footer'):
                if any(i.get('type') == 'footer' for i in params if 'type' in i):
                    if [i for i in params if i.get('type') == 'footer'][0].get('parameters')[0].get('type') == 'text':
                        footer_text = [i for i in params if i.get('type') == 'footer'][0].get('parameters')[0].get(
                            'text')
                        footer.update({"type": "text",
                                       "text": footer_text})
                    temp = False
                    for i in params:
                        if 'type' in i and i.get('type') == 'footer':
                            temp = i
                    if temp:
                        params.remove(temp)
                else:
                    if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'footer'):
                        footer_text = wa_template_id.components_ids.filtered(
                            lambda x: x.type == 'footer').text
                        footer.update({"text": footer_text})
            template_type = wa_template_id.components_ids.filtered(
                lambda x: x.type == 'interactive').type
            interactive_type = wa_template_id.components_ids.filtered(
                lambda x: x.type == 'interactive').interactive_type

            interactive_product = False
            if interactive_type == 'product' or interactive_type == 'button':
                interactive_product = {
                    "type": interactive_type,
                    "header": header or '',
                    "body": body or '',
                    "footer": footer or '',
                    "action": params[0]
                }
            if interactive_type == 'product_list':
                interactive_product = {
                    "type": interactive_type,
                    "header": header or '',
                    "body": body or '',
                    "footer": footer or '',
                    "action": params[0]
                }
            if interactive_type == 'list':
                interactive_product = {
                    "type": interactive_type,
                    "header": header or '',
                    "body": body or '',
                    "footer": footer or '',
                    "action": params[0]
                }

            payload = json.dumps({
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": partner.phone or partner.mobile,
                "type": template_type,
                "interactive": interactive_product
            })
            headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + self.graph_api_token
            }
            try:
                answer = requests.post(url, headers=headers, data=payload)
            except requests.exceptions.ConnectionError:
                raise UserError(
                    ("please check your internet connection."))
            if answer.status_code != 200:
                if 'message' in json.loads(answer.text).get('error') and 'error_data' not in json.loads(
                        answer.text).get('error'):
                    dict = json.loads(answer.text).get('error').get('message')
                    raise UserError(_(dict))
                elif 'message' in json.loads(answer.text).get('error') and 'error_data' in json.loads(
                        answer.text).get('error'):
                    dict = json.loads(answer.text).get('error').get('message') + '\n \n' + json.loads(
                        answer.text).get('error').get('error_data').get('details')
                    raise UserError(_(dict))
            return answer
        else:
            raise UserError(
                ("please authenticated your whatsapp."))

    def graph_api_send_mpm_template(self, template, language, namespace, partner, params):
        if self.graph_api_authenticated:
            url = self.graph_api_url + self.graph_api_instance_id + "/messages"
            header_text = False
            header = {}
            wa_template_id = self.env['wa.template'].search(
                [('name', '=', template), ('template_type', '=', 'interactive')], limit=1) or self.env.context.get(
                'wa_template')
            # context_wa_template_id = self.env.context.get('wa_template')
            component_ids = wa_template_id.components_ids
            if wa_template_id and component_ids.filtered(lambda x: x.type == 'header'):
                if any(i.get('type') == 'header' for i in params if 'type' in i):
                    if [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get('type') == 'text':
                        header_text = [i for i in params if i.get('type') == 'header'][0].get('parameters')[0].get(
                            'text')
                        header.update({"type": "text",
                                       "text": header_text})
                    else:
                        for component in component_ids:
                            if component.formate == 'media':
                                if component.formate_media_type == 'static':
                                    IrConfigParam = self.env[
                                        "ir.config_parameter"
                                    ].sudo()
                                    base_url = IrConfigParam.get_param(
                                        "web.base.url", False
                                    )
                                    attachment_ids = component.attachment_ids
                                    if component.media_type == 'document':
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "document": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                    "filename": self.env[
                                                        "ir.attachment"
                                                    ]
                                                    .sudo()
                                                    .browse(
                                                        attachment_ids.ids[
                                                            0
                                                        ]
                                                    )
                                                    .name,
                                                },
                                            })
                                    if component.media_type == "video":
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "video": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                },
                                            })
                                    if component.media_type == "image":
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "image": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                },
                                            })

                else:
                    if wa_template_id and wa_template_id.components_ids.filtered(
                            lambda x: x.type == 'header').formate == 'text':
                        header_text = wa_template_id.components_ids.filtered(
                            lambda x: x.type == 'header').text
                        header.update({"type": "text",
                                       "text": header_text})
                    else:
                        for component in component_ids:
                            if component.formate == 'media':
                                if component.formate_media_type == 'static':
                                    IrConfigParam = self.env[
                                        "ir.config_parameter"
                                    ].sudo()
                                    base_url = IrConfigParam.get_param(
                                        "web.base.url", False
                                    )
                                    attachment_ids = component.attachment_ids
                                    if component.media_type == 'document':
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "document": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                    "filename": self.env[
                                                        "ir.attachment"
                                                    ]
                                                    .sudo()
                                                    .browse(
                                                        attachment_ids.ids[
                                                            0
                                                        ]
                                                    )
                                                    .name,
                                                },
                                            })
                                    if component.media_type == "video":
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "video": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                },
                                            })
                                    if component.media_type == "image":
                                        if attachment_ids:
                                            header.update(
                                                {"type": component.media_type}
                                            )
                                            header.update({
                                                "image": {
                                                    "link": base_url + "/web/content/" + str(attachment_ids.ids[0]),
                                                },
                                            })
            body_text = False
            body = {}
            if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'body'):
                if any(i.get('type') == 'body' for i in params if 'type' in i):
                    if [i for i in params if i.get('type') == 'body'][0].get('parameters')[0].get('type') == 'text':
                        body_text = [i for i in params if i.get('type') == 'body'][0].get('parameters')[0].get('text')
                        body.update({"type": "text",
                                     "text": body_text})
                else:
                    if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'body'):
                        body_text = wa_template_id.components_ids.filtered(
                            lambda x: x.type == 'body').text
                        body.update({"text": body_text})

            footer_text = False
            footer = {}
            if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'footer'):
                if any(i.get('type') == 'footer' for i in params if 'type' in i):
                    if [i for i in params if i.get('type') == 'footer'][0].get('parameters')[0].get('type') == 'text':
                        footer_text = [i for i in params if i.get('type') == 'footer'][0].get('parameters')[0].get(
                            'text')
                        footer.update({"type": "text",
                                       "text": footer_text})
                else:
                    if wa_template_id and wa_template_id.components_ids.filtered(lambda x: x.type == 'footer'):
                        footer_text = wa_template_id.components_ids.filtered(
                            lambda x: x.type == 'footer').text
                        footer.update({"text": footer_text})
            template_type = wa_template_id.components_ids.filtered(
                lambda x: x.type == 'interactive').type
            interactive_type = wa_template_id.components_ids.filtered(
                lambda x: x.type == 'interactive').interactive_type

            interactive_product = False
            if interactive_type == 'product' or interactive_type == 'button':
                interactive_product = {
                    "type": interactive_type,
                    "header": header or '',
                    "body": body or '',
                    "footer": footer or '',
                    "action": params[0]
                }
            if interactive_type == 'product_list':
                interactive_product = {
                    "type": interactive_type,
                    "header": header or '',
                    "body": body or '',
                    "footer": footer or '',
                    "action": params[0]
                }
            if interactive_type == 'list':
                interactive_product = {
                    "type": interactive_type,
                    "header": header or '',
                    "body": body or '',
                    "footer": footer or '',
                    "action": params[0]
                }

            payload = json.dumps({
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": partner.mobile,
                "type": template_type,
                "interactive": interactive_product
            })
            headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + self.graph_api_token
            }
            try:
                answer = requests.post(url, headers=headers, data=payload)
            except requests.exceptions.ConnectionError:
                raise UserError(
                    ("please check your internet connection."))
            if answer.status_code != 200:
                if 'message' in json.loads(answer.text).get('error') and 'error_data' not in json.loads(
                        answer.text).get('error'):
                    dict = json.loads(answer.text).get('error').get('message')
                    raise UserError(_(dict))
                elif 'message' in json.loads(answer.text).get('error') and 'error_data' in json.loads(
                        answer.text).get('error'):
                    dict = json.loads(answer.text).get('error').get('message') + '\n \n' + json.loads(
                        answer.text).get('error').get('error_data').get('details')
                    raise UserError(_(dict))
            return answer
        else:
            raise UserError(
                ("please authenticated your whatsapp."))

    def get_docs_parameters(self, doc_type, doc_id):
        """
        This method will prepare the list of dict for the params required to send WA API.
        """
        base_url = self.env.company.get_base_url()
        parameters = [
            {
                "type": doc_type,
                doc_type: {
                    "link": base_url + "/web/content/" + str(doc_id.id),
                    "filename": doc_id.sudo().name,
                },
            }
        ]
        if doc_type == 'image':
            parameters[0][doc_type]['link'] += '/datas'
            parameters[0][doc_type].pop('filename')
        if doc_type == 'video':
            parameters[0][doc_type].pop('filename')
        return parameters or []

    def get_channel_whatsapp(self, partner, user):
        channel = self.env['discuss.channel'].sudo()
        if not partner or not user:
            return channel
        provider_channel_id = partner.channel_provider_line_ids.filtered(lambda s: s.provider_id.id == self.id)
        if provider_channel_id:
            channel |= provider_channel_id.channel_id
            if user.partner_id.id not in channel.channel_partner_ids.ids and user.has_group(
                    "base.group_user") and user.has_group("all_in_one_whatsapp_odoo_community.whatsapp_group_user"):
                channel.sudo().write({"channel_partner_ids": [(4, user.partner_id.id)]})
        else:
            name = partner.mobile
            channel |= self.env['discuss.channel'].sudo().create(
                {
                    "channel_type": "chat",
                    "name": name,
                    "whatsapp_channel": True,
                    "channel_partner_ids": [(4, partner.id)],
                }
            )
            channel.sudo().write({
                "channel_member_ids": [(5, 0, 0)]
                                      + [
                                          (
                                              0,
                                              0,
                                              {"partner_id": line_vals},
                                          )
                                          for line_vals in [partner.id, user.partner_id.id]
                                      ]
            })
            partner.sudo().write({"channel_provider_line_ids": [
                (0, 0, {"channel_id": channel.id, "provider_id": self.id})]})
        if channel:
            self._add_multi_agents(channel)
        return channel

    def _add_multi_agents(self, channel):
        for rec in self:
            if rec.user_ids:
                if self.company_id and (self.company_id._fields.get('wa_chatbot_id') and self.company_id.wa_chatbot_id):
                    return
                else:
                    for user in rec.user_ids:
                        channel_partner = channel.channel_partner_ids.filtered(lambda x: x.id == user.partner_id.id)
                        if not channel_partner:
                            channel.sudo().write(
                                {'channel_partner_ids': [(4, user.partner_id.id)]})
                        mail_channel_partner = self.env[
                            'discuss.channel.member'].sudo().search(
                            [('channel_id', '=', channel.id),
                             ('partner_id', '=', user.partner_id.id)])
                        if not mail_channel_partner.is_pinned:
                            mail_channel_partner.write({'is_pinned': True})

    def _get_interactive_template_params(self, component):
        self.ensure_one()
        template_dict = {}
        if component.interactive_type == 'product_list':
            if component.interactive_product_list_ids:
                section = []
                for product in component.interactive_product_list_ids:
                    product_items = []

                    for products in product.product_list_ids:
                        product_item = {
                            "product_retailer_id": products.product_retailer_id
                        }

                        product_items.append(product_item)

                    section.append({
                        "title": product.main_title,
                        "product_items": product_items
                    })

                action = {
                    "catalog_id": component.catalog_id,
                    "sections": section
                }

                template_dict.update(action)

        elif component.interactive_type == 'button':
            if component.interactive_button_ids:
                buttons = []
                for btn_id in component.interactive_button_ids:
                    buttons.append({
                        "type": "reply",
                        "reply": {
                            "id": btn_id.id,
                            "title": btn_id.title
                        }
                    })
                action = {
                    "buttons": buttons
                }

                template_dict.update(action)

        elif component.interactive_type == 'list':
            if component.interactive_list_ids:
                section = []
                for list_id in component.interactive_list_ids:
                    rows = []
                    for lists in list_id.title_ids:
                        title_ids = {
                            "id": lists.id,
                            "title": lists.title,
                            "description": lists.description or ''
                        }
                        rows.append(title_ids)

                    section.append({
                        'title': list_id.main_title,
                        'rows': rows
                    })
                action = {
                    "button": list_id.main_title,
                    "sections": section
                }
                template_dict.update(action)

        elif component.interactive_type == 'product':
            action = {
                "catalog_id": component.catalog_id,
                "product_retailer_id": component.product_retailer_id
            }
            template_dict.update(action)
        elif component.interactive_type == 'catalog_message':
            action = {
                'name': 'catalog_message',
                'parameters': {
                    "thumbnail_product_retailer_id": component.product_retailer_id},
            }
            template_dict.update(action)
        return template_dict

    def _get_remove_unwanted_mail_message(self,message_id):
        """
        This method will call when an error occurs, so mail message removal process necessary
        """
        if message_id:
            mail_message = self.env['mail.message'].browse(message_id).unlink()

