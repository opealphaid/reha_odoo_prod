from odoo import models, api, fields, tools
import json
from odoo.exceptions import UserError, ValidationError
from datetime import datetime

image_type = ['image/avif', 'image/bmp', 'image/gif', 'image/vnd.microsoft.icon', 'image/jpeg', 'image/png',
              'image/svg+xml', 'image/tiff', 'image/webp']
document_type = ['application/xhtml+xml', 'application/vnd.ms-excel',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/xml',
                 'application/vnd.mozilla.xul+xml', 'application/zip',
                 'application/x-7z-compressed', 'application/x-abiword', 'application/x-freearc',
                 'application/vnd.amazon.ebook', 'application/octet-stream', 'application/x-bzip',
                 'application/x-bzip2', 'application/x-cdf', 'application/x-csh', 'application/msword',
                 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                 'application/vnd.ms-fontobject', 'application/epub+zip', 'application/gzip',
                 'application/java-archive', 'application/json', 'application/ld+json',
                 'application/vnd.apple.installer+xml', 'application/vnd.oasis.opendocument.presentation',
                 'application/vnd.oasis.opendocument.spreadsheet', 'application/vnd.oasis.opendocument.text',
                 'application/ogg', 'application/pdf', 'application/x-httpd-php', 'application/vnd.ms-powerpoint',
                 'application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/vnd.rar',
                 'application/rtf', 'application/x-sh', 'application/x-tar', 'application/vnd.visio']
audio_type = ['audio/aac', 'audio/midi', 'audio/x-midi', 'audio/mpeg', 'audio/ogg', 'audio/opus', 'audio/wav',
              'audio/webm', 'audio/3gpp', 'audio/3gpp2']
video_type = ['video/x-msvideo', 'video/mp4', 'video/mpeg', 'video/ogg', 'video/mp2t', 'video/webm', 'video/3gpp',
              'video/3gpp2']


class WhatsappHistory(models.Model):
    _description = 'Whatsapp History'
    _name = 'whatsapp.history'
    _rec_name = 'phone'

    provider_id = fields.Many2one('provider', 'Provider', readonly=True)
    author_id = fields.Many2one('res.partner', 'Author', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Recipient', readonly=True)
    phone = fields.Char(string="Whatsapp Number", readonly=True)
    # phn_no = fields.Char('Phone Number')
    message = fields.Char('Message', readonly=True)
    type = fields.Selection([
        ('in queue', 'In queue'),
        ('sent', 'Sent'),
        ('delivered', 'delivered'),
        ('received', 'Received'), ('read', 'Read'), ('fail', 'Fail')], string='Type', default='in queue', readonly=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'wa_history_attachment_rel',
        'wa_message_id', 'wa_attachment_id',
        string='Attachments', readonly=True)
    message_id = fields.Char("Message ID", readonly=True)
    mail_message_id = fields.Many2one('mail.message')
    fail_reason = fields.Char("Fail Reason", readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, readonly=True)
    date = fields.Datetime('Date', default=fields.Datetime.now, readonly=True)
    model = fields.Char('Related Document Model', index=True, readonly=True)
    active = fields.Boolean('Active', default=True)
    rec_id = fields.Integer("Related Model ID", readonly=True)

    @api.onchange('partner_id')
    def _onchange_partner(self):
        """
        phone change to mobile
        """
        for rec in self:
            rec.phone = rec.partner_id.mobile

    def _get_variable_params_dict(self, variable, object_data):
        parameter_dict = {}
        if variable.field_id.ttype in ['text', 'char', 'selection']:
            parameter_dict.update(
                {'type': 'text',
                 'text': object_data.get(variable.field_id.name) if object_data.get(
                     variable.field_id.name) else variable.free_text or ''})
        elif variable.field_id.ttype in ['integer', 'float']:
            parameter_dict.update({'type': 'text',
                                   'text': str(object_data.get(variable.field_id.name)) if object_data.get(
                                       variable.field_id.name) else variable.free_text or ''})
        elif variable.field_id.ttype == 'monetary':
            currency_id = object_data.get('currency_id')[0]
            currency = self.env['res.currency'].browse(currency_id)
            text = currency.position == 'after' and str(
                object_data.get(variable.field_id.name)) + currency.symbol or currency.symbol + str(
                object_data.get(variable.field_id.name)) if object_data.get(
                variable.field_id.name) else variable.free_text or ''
            parameter_dict.update(
                {'type': 'text', 'text': text})
        elif variable.field_id.ttype == 'html':
            if object_data.get(variable.field_id.name):
                parameter_dict.update({'type': 'text',
                                       'text': tools.html2plaintext(
                                           object_data.get(variable.field_id.name)) if object_data.get(
                                           variable.field_id.name) else variable.free_text or ''})
        elif variable.field_id.ttype in ["date", "datetime"]:
            parameter_dict.update(
                {
                    "type": "text",
                    "text": object_data.get(variable.field_id.name).strftime("%m/%d/%Y") if object_data.get(
                        variable.field_id.name) else variable.free_text or '',
                }
            )
        elif variable.field_id.ttype == 'many2one':
            parameter_dict.update({'type': 'text',
                                   'text': object_data.get(variable.field_id.name)[1] if object_data.get(
                                       variable.field_id.name) else variable.free_text or ''})
        else:
            parameter_dict.update({'type': 'text',
                                   'text': variable.free_text if variable.free_text else ''})
        return parameter_dict

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('is_chatbot'):
                vals.pop('is_chatbot')
                return super(WhatsappHistory, self).create(vals)
            if vals.get('is_commerce_manager', False):
                vals.pop('is_commerce_manager')
                return super(WhatsappHistory, self).create(vals)
            if vals.get('is_dynamic_booking_chatbot', False):
                vals.pop('is_dynamic_booking_chatbot')
                return super(WhatsappHistory, self).create(vals)
            
            res = super(WhatsappHistory, self).create(vals)

            if res.provider_id and res.partner_id and res.partner_id.mobile and \
                    res.type != 'received' and not self.env.context.get('whatsapp_application'):
                if self.env.context.get('template_send'):
                    wa_template = self.env.context.get('wa_template')
                    params = []
                    if wa_template and wa_template.template_type == 'interactive':
                        for component in wa_template.components_ids:
                            template_dict = res.provider_id._get_interactive_template_params(component)
                            if bool(template_dict):
                                params.append(template_dict)
                        try:
                            answer = res.provider_id.send_mpm_template(wa_template.name,
                                                                       wa_template.language,
                                                                       wa_template.namespace, res.partner_id,
                                                                       params)
                        except UserError as e:
                            if vals.get('mail_message_id'):
                                res.provider_id._get_remove_unwanted_mail_message(vals.get('mail_message_id'))
                            if res:
                                res.unlink()

                            raise ValidationError(str(e))

                        if answer.status_code == 200:
                            dict = json.loads(answer.text)
                            if res.provider_id.provider == 'graph_api':  # if condition for Graph API
                                if 'messages' in dict and dict.get('messages') and dict.get('messages')[0].get(
                                        'id'):
                                    vals['message_id'] = dict.get('messages')[0].get('id')
                                    if self.env.context.get('wa_messsage_id'):
                                        self.env.context.get('wa_messsage_id').wa_message_id = \
                                            dict.get('messages')[0].get('id')
                            else:
                                if 'sent' in dict and dict.get('sent'):
                                    message_id = dict['id']
                                    if self.env.context.get('wa_messsage_id'):
                                        self.env.context.get('wa_messsage_id').wa_message_id = dict['id']
                                else:
                                    if not self.env.context.get('cron'):
                                        if 'message' in dict:
                                            raise UserError(
                                                (dict.get('message')))
                                        if 'error' in dict:
                                            raise UserError(
                                                (dict.get('error').get('message')))
                                    else:
                                        vals.update({'type': 'fail'})
                                        if 'error' in dict:
                                            vals.update({'fail_reason': dict.get('error').get('message')})
                        return res
                    else:
                        for component in wa_template.components_ids:
                            object_data = self.env[wa_template.model_id.model].search_read(
                                [('id', '=', self.env.context.get('active_model_id'))])[0]

                            template_dict = {}
                            cards = []
                            if component.type in ['body', 'footer'] and component.variables_ids:
                                template_dict.update({'type': component.type})
                                parameters = []
                                for variable in component.variables_ids:
                                    parameters.append(res._get_variable_params_dict(variable, object_data))
                                    template_dict.update({'parameters': parameters})
                                for length, var in enumerate(component.variables_ids):
                                    st = '{{%d}}' % (length + 1)
                                    if var.field_id.model or var.free_text:
                                        mail_message = self.env['mail.message'].browse(vals.get('mail_message_id', None))
                                        value = object_data.get(var.field_id.name) if var.field_id.name else var.free_text
                                        if mail_message:
                                            mail_message.write({
                                                'body': mail_message.body.replace(st, str(value[1] if isinstance(value, tuple) else value))
                                            })
                                            res.update({
                                                'message': tools.html2plaintext(mail_message.body.replace(st, str(value[1] if isinstance(value, tuple) else value)))
                                            })

                            if component.type == "header":
                                if component.formate == "text" and component.variables_ids:
                                    template_dict.update(
                                        {"type": component.type}
                                    )
                                    parameters = []
                                    for variable in component.variables_ids:
                                        parameters.append(res._get_variable_params_dict(variable, object_data))
                                        template_dict.update({'parameters': parameters})
                                if component.formate == "media" and component.formate_media_type in ["dynamic", "static"]:
                                    if component.media_type in ["image", "document", "video"] and (self.env.context.get("attachment_ids") or component.attachment_ids):
                                        template_dict.update({"type": component.type})
                                        doc_attachment = self.env.context.get("attachment_ids") if component.formate_media_type == "dynamic" else component.attachment_ids
                                        parameters = res.provider_id.get_docs_parameters(doc_type=component.media_type, doc_id=fields.first(doc_attachment))
                                        template_dict.update({"parameters": parameters})
                            if component.type == "buttons":
                                wa_template._get_send_button_params(component, object_data, params)
                            if component.type == "limited_time_offer":
                                template_dict.update({'type': component.type})
                                parameter = []
                                limited_time_offer = {
                                    "type": "limited_time_offer",
                                    "limited_time_offer": {
                                        'expiration_time_ms': datetime.timestamp(
                                            component.limited_offer_exp_date) * 1000
                                    }
                                }
                                parameter.append(limited_time_offer)
                                template_dict.update({'parameters': parameter})
                            if component.type == 'carousel':
                                wa_template._get_carousel_params(component, object_data, res.provider_id, cards)
                            if bool(template_dict):
                                params.append(template_dict)
                            if cards:
                                params.append({"type": "CAROUSEL", "cards": cards})
                        try:
                            answer = res.provider_id.send_template(wa_template.name, wa_template.language,
                                                                   wa_template.namespace, res.partner_id, params)
                        except UserError as e:
                            if vals.get('mail_message_id'):
                                res.provider_id._get_remove_unwanted_mail_message(vals.get('mail_message_id'))
                            if res:
                                res.unlink()
                            raise ValidationError(str(e))
                        if answer.status_code == 200:
                            dict = json.loads(answer.text)
                            if res.provider_id.provider == 'graph_api':  # if condition for Graph API
                                if 'messages' in dict and dict.get('messages') and dict.get('messages')[0].get(
                                        'id'):
                                    res.message_id = dict.get('messages')[0].get('id')
                                    res.mail_message_id.wa_message_id = dict.get('messages')[0].get('id')
                                    if self.env.context.get('wa_messsage_id'):
                                        self.env.context.get('wa_messsage_id').wa_message_id = dict.get('messages')[
                                            0].get('id')
                else:
                    if res.message:
                        answer = False
                        if 'message_parent_id' in self.env.context:
                            parent_msg = self.env['mail.message'].sudo().search(
                                [('id', '=', self.env.context.get('message_parent_id').id)])
                            answer = res.provider_id.send_message(res.partner_id, res.message,
                                                                  parent_msg.wa_message_id)
                        else:
                            answer = res.provider_id.send_message(res.partner_id, res.message)
                        if answer.status_code == 200:
                            dict = json.loads(answer.text)
                            if res.provider_id.provider == 'graph_api':  # if condition for Graph API
                                if 'messages' in dict and dict.get('messages') and dict.get('messages')[0].get(
                                        'id'):
                                    res.message_id = dict.get('messages')[0].get('id')
                                    if self.env.context.get('wa_messsage_id'):
                                        self.env.context.get('wa_messsage_id').wa_message_id = \
                                            dict.get('messages')[0].get('id')

                            else:
                                if 'sent' in dict and dict.get('sent'):
                                    res.message_id = dict['id']
                                    if self.env.context.get('wa_messsage_id'):
                                        self.env.context.get('wa_messsage_id').wa_message_id = dict['id']
                                else:
                                    if not self.env.context.get('cron'):
                                        if 'message' in dict:
                                            raise UserError(
                                                (dict.get('message')))
                                        if 'error' in dict:
                                            raise UserError(
                                                (dict.get('error').get('message')))
                                    else:
                                        res.write({'type': 'fail'})
                                        if 'message' in dict:
                                            res.write({'fail_reason': dict.get('message')})

                    if res.attachment_ids:
                        for attachment_id in res.attachment_ids:
                            if res.provider_id.provider == 'graph_api':
                                sent_type = ''
                                if attachment_id.mimetype in image_type:
                                    sent_type += 'image'
                                elif attachment_id.mimetype in document_type:
                                    sent_type += 'document'
                                elif attachment_id.mimetype in audio_type:
                                    sent_type += 'audio'
                                elif attachment_id.mimetype in video_type:
                                    sent_type += 'video'
                                else:
                                    sent_type += 'image'

                                answer = res.provider_id.send_image(attachment_id)
                                if answer.status_code == 200:
                                    dict = json.loads(answer.text)
                                    getimagebyid = res.provider_id.get_image_by_id(dict.get('id'), res.partner_id,
                                                                                   sent_type, attachment_id)
                                    if getimagebyid.status_code == 200:
                                        imagedict = json.loads(getimagebyid.text)
                                    if 'messages' in imagedict and imagedict.get('messages'):
                                        res.message_id = imagedict.get('messages')[0].get('id', '')
                                        if self.env.context.get('wa_messsage_id'):
                                            self.env.context.get(
                                                'wa_messsage_id').wa_message_id = imagedict.get('messages')[
                                                0].get('id', '') if imagedict.get(
                                                'messages') else imagedict.get('id', '')
                                    else:
                                        if not self.env.context.get('cron'):
                                            raise UserError(
                                                (imagedict.get('message', 'Something went wrong')))
                                        if 'error' in imagedict:
                                            raise UserError(
                                                (imagedict.get('error').get('message')))
                                        else:
                                            res.write({'type': 'fail',
                                                       'fail_reason': imagedict.get('message', '')})
            return res
