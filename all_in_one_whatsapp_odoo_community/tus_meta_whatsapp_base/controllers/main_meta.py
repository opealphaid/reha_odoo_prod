from odoo.fields import first
from odoo.http import request
from odoo import http, _, tools
import requests
import json
import phonenumbers
import datetime
from odoo.exceptions import UserError, ValidationError
from phonenumbers.phonenumberutil import (
    region_code_for_country_code,
)
import base64
from werkzeug.exceptions import Forbidden

from http import HTTPStatus


class WebHook2(http.Controller):
    _webhook_url = '/graph_tus/webhook'
    _meta_fb_url = '/graph_tus/webhook'

    @http.route(_webhook_url, type='http', methods=['GET'], auth='public', csrf=False)
    def facebook_webhook(self, **kw):
        verify_token = kw.get('hub.verify_token')
        hub_mode = kw.get('hub.mode')
        hub_challenge = kw.get('hub.challenge')
        if not (verify_token and hub_mode and hub_challenge):
            return Forbidden()
        provider_id = request.env['provider'].sudo().search([('verify_token', '=', verify_token)])
        if hub_mode == 'subscribe' and provider_id:
            response = request.make_response(hub_challenge)
            response.status_code = HTTPStatus.OK
            return response
        response = request.make_response({})
        response.status_code = HTTPStatus.FORBIDDEN
        return response

    def get_url(self, provider, media_id, phone_number_id):
        if provider.graph_api_authenticated:
            url = provider.graph_api_url + media_id + "?phone_number_id=" + phone_number_id + "&access_token=" + provider.graph_api_token
            headers = {'Content-type': 'application/json'}
            payload = {}
            try:
                answer = requests.request("GET", url, headers=headers, data=payload)
            except requests.exceptions.ConnectionError:
                raise UserError(
                    ("please check your internet connection."))
            return answer
        else:
            raise UserError(
                ("please authenticated your whatsapp."))

    def get_media_data(self, url, provider):
        payload = {}
        headers = {
            'Authorization': 'Bearer ' + provider.graph_api_token
        }
        response = requests.request("GET", url, headers=headers, data=payload)
        decoded = base64.b64encode(response.content)
        return decoded

    def _get_received_attachment(self, message_obj, provider, mail_message, history):
        attachment_value = {}
        media_id = ''
        if message_obj.get('type') == 'image':
            media_id = message_obj.get('image').get('id')
            attachment_value.update({'name': media_id,
                                     'type': 'binary',
                                     'mimetype': message_obj.get('image').get('mime_type') if message_obj.get(
                                         'image') and message_obj.get('image').get('mime_type') else 'image/jpeg'})
            mail_message.update({'body': message_obj.get('image').get(
                'caption') if 'image' in message_obj and 'caption' in message_obj.get(
                'image') else ''})
            history.update({'message': message_obj.get('image').get(
                'caption') if 'image' in message_obj and 'caption' in message_obj.get(
                'image') else ''})
        elif message_obj.get('type') == 'video':
            media_id = message_obj.get('video').get('id')
            attachment_value.update({'name': 'whatsapp_video',
                                     'type': 'binary',
                                     'mimetype': message_obj.get('video').get('mime_type') if message_obj.get(
                                         'video') and message_obj.get('video').get('mime_type') else 'video/mp4'})
            mail_message.update({'body': message_obj.get('video').get(
                'caption') if 'video' in message_obj and 'caption' in message_obj.get(
                'video') else ''})
            history.update({'message': message_obj.get('video').get(
                'caption') if 'video' in message_obj and 'caption' in message_obj.get(
                'video') else ''})
        elif message_obj.get('type') == 'document':
            media_id = message_obj.get('document').get('id')
            attachment_value.update({'name': message_obj.get('document').get('filename'),
                                     'type': 'binary',
                                     'mimetype': message_obj.get('document').get('mime_type') if message_obj.get(
                                         'document') and message_obj.get('document').get(
                                         'mime_type') else 'application/pdf'})
            mail_message.update({'body': message_obj.get('document').get(
                'caption') if 'document' in message_obj and 'caption' in message_obj.get(
                'document') else ''})
            history.update({'message': message_obj.get('document').get(
                'caption') if 'document' in message_obj and 'caption' in message_obj.get(
                'document') else ''})
        elif message_obj.get('type') == 'audio':
            media_id = message_obj.get('audio').get('id')
            attachment_value.update({'name': 'whatsapp_audio',
                                     'type': 'binary',
                                     'mimetype': message_obj.get('audio').get('mime_type') if message_obj.get(
                                         'audio') and message_obj.get('audio').get('mime_type') and
                                                  message_obj.get('audio').get('mime_type') != 'audio/ogg; codecs=opus' else 'audio/mpeg'})
            mail_message.update({'body': message_obj.get('audio').get(
                'caption') if 'audio' in message_obj and 'caption' in message_obj.get(
                'audio') else ''})
            history.update({'message': message_obj.get('audio').get(
                'caption') if 'audio' in message_obj and 'caption' in message_obj.get(
                'audio') else ''})
        elif message_obj.get('type') == 'sticker':
            media_id = message_obj.get('sticker').get('id')
            attachment_value.update({'name': 'whatsapp_sticker',
                                     'type': 'binary',
                                     'mimetype': message_obj.get('sticker').get('mime_type') if message_obj.get(
                                         'sticker') and message_obj.get('sticker').get('mime_type') else 'image/webp'})
            mail_message.update({'body': message_obj.get('sticker').get(
                'caption') if 'sticker' in message_obj and 'caption' in message_obj.get(
                'sticker') else ''})
            history.update({'message': message_obj.get('sticker').get(
                'caption') if 'sticker' in message_obj and 'caption' in message_obj.get(
                'sticker') else ''})
        if media_id:
            geturl = self.get_url(provider, media_id, provider.graph_api_instance_id)
            dict = json.loads(geturl.text)
            decoded = self.get_media_data(dict.get('url'), provider)
            attachment_value.update({'datas': decoded})
            attachment = request.env['ir.attachment'].sudo().create(attachment_value)

            return attachment, mail_message, history

    @http.route(_meta_fb_url, type='json', methods=['POST'], auth='public', csrf=False)
    def meta_webhook(self, **kw):
        wa_dict = {}

        data = json.loads(request.httprequest.data.decode('utf-8'))
        wa_dict.update({'messages': data.get('messages')})
        provider = request.env['provider'].sudo()
        data_value_obj = data and data.get('entry') and data.get('entry')[0].get('changes') and \
                         data.get('entry')[0].get('changes')[0].get('value', False)
        if data_value_obj:
            if data_value_obj.get('metadata') and \
                    data_value_obj.get('metadata').get(
                        'phone_number_id'):
                phone_number_id = data_value_obj.get('metadata').get(
                    'phone_number_id')
                provider |= provider.search(
                    [('graph_api_authenticated', '=', True),
                     ('graph_api_instance_id', '=', phone_number_id)],
                    limit=1)
                wa_dict.update({'provider': provider})
                if not provider:
                    return wa_dict

            if data_value_obj.get('statuses'):
                channel = request.env['discuss.channel']
                for acknowledgment in data_value_obj.get('statuses'):
                    wp_msgs = request.env['whatsapp.history'].sudo().search(
                        [('message_id', '=', acknowledgment.get('id'))], limit=1)
                    partner = provider.user_id.partner_id.sudo().search(
                        ['|', ('phone', '=', acknowledgment.get('recipient_id')),
                         ('mobile', '=', acknowledgment.get('recipient_id'))], limit=1)
                    if partner:
                        channel |= provider.get_channel_whatsapp(partner, provider.user_id)
                    if wp_msgs:
                        wa_mail_message = request.env['mail.message'].sudo().search(
                            [('wa_message_id', '=', acknowledgment.get('id'))], limit=1)
                        if wp_msgs and wp_msgs.type != acknowledgment.get('status') and wp_msgs.type != 'read':
                            if acknowledgment.get('status') in ['sent', 'delivered', 'read']:
                                wp_msgs.sudo().write({'type': acknowledgment.get('status')})
                            elif acknowledgment.get('status') == 'failed':
                                wp_msgs.sudo().write(
                                    {'type': 'fail', 'fail_reason': acknowledgment.get('errors')[0].get('title')})

                        if wa_mail_message and wa_mail_message.wp_status != acknowledgment.get('status') and wa_mail_message.wp_status != 'read':
                            temp_id = wa_mail_message.id + datetime.datetime.now().second / 100
                            if acknowledgment.get('status') in ['sent', 'delivered', 'read']:
                                wa_mail_message.sudo().with_context(temporary_id=temp_id).write(
                                    {'wp_status': acknowledgment.get('status')})
                            elif acknowledgment.get('status') == 'failed':
                                wa_mail_message.sudo().with_context(temporary_id=temp_id).write(
                                    {'wp_status': 'fail', 'wa_delivery_status': acknowledgment.get('status'),
                                     'wa_error_message': acknowledgment.get('errors')[0].get('title')})
                            request.env.cr.commit()
                            if wa_mail_message:
                                channel.sudo()._notify_thread(wa_mail_message)

            is_tus_discuss_installed = request.env['ir.module.module'].sudo().search(
                [('state', '=', 'installed'), ('name', '=', 'tus_meta_wa_discuss')])
            if not is_tus_discuss_installed:
                return wa_dict
            if provider.graph_api_authenticated:
                user_partner = provider.user_id.partner_id
                if data_value_obj.get('messages'):
                    for mes in data_value_obj.get('messages'):
                        wa_dict.update({'chat': True})
                        history = bool(request.env['whatsapp.history'].sudo().search_count(
                            [('message_id', '=', mes.get('id'))]))
                        if history:
                            return wa_dict
                        pn = phonenumbers.parse('+' + mes.get('from'))
                        country_code = region_code_for_country_code(pn.country_code)
                        country_id = request.env['res.country'].sudo().search(
                            [('code', '=', country_code)], limit=1)
                        partners = request.env['res.partner'].sudo().search(
                            ['|', ('phone', 'in',[mes.get('from'),pn.national_number]), ('mobile', 'in', [mes.get('from'),pn.national_number])])
                        wa_dict.update({'partners': partners})
                        if not partners:
                            partners = request.env['res.partner'].sudo().create(
                                {'name': data.get('entry')[0].get('changes')[0].get('value').get('contacts')[
                                    0].get('profile').get('name'), 'country_id': country_id.id,
                                 'is_whatsapp_number': True,
                                 'mobile': mes.get('from')})

                        for partner in partners:
                            channel = provider.get_channel_whatsapp(partner, provider.user_id)

                            message_values = {
                                'author_id': partner.id,
                                'email_from': partner.email or '',
                                'model': 'discuss.channel',
                                'message_type': 'wa_msgs',
                                'wa_message_id': mes.get('id'),
                                'isWaMsgs': True,
                                'subtype_id': request.env['ir.model.data'].sudo()._xmlid_to_res_id(
                                    'mail.mt_comment'),
                                'partner_ids': [(4, partner.id)],
                                'res_id': channel.id,
                                'reply_to': partner.email,
                                'company_id': provider.company_id.id,
                            }
                            vals = {
                                'provider_id': provider.id,
                                'author_id': user_partner.id,
                                'message_id': mes.get('id'),
                                'type': 'received',
                                'partner_id': partner.id,
                                'phone': partner.mobile,
                                'attachment_ids': False,
                                'company_id': provider.company_id.id,
                            }
                            if mes.get('type') == 'text':
                                message_values.update({
                                    'body': mes.get('text').get('body'),
                                })
                                vals.update({'message': mes.get('text').get('body')})
                            elif mes.get('type') == 'location':
                                # phone change to mobile
                                lat = mes.get('location').get('latitude')
                                lag = mes.get('location').get('longitude')
                                message_values.update({
                                    'body': "<a href='https://www.google.com/maps/search/?api=1&query=" + str(
                                        lat) + "," + str(
                                        lag) + "' target='_blank' class='btn btn-primary'>Google Map</a>",
                                })
                                vals.update(
                                    {'message': "<a href='https://www.google.com/maps/search/?api=1&query=" + str(
                                        lat) + "," + str(
                                        lag) + "' target='_blank' class='btn btn-primary'>Google Map</a>"})
                            elif mes.get('type') in ['image', 'video', 'document', 'audio', 'sticker']:
                                attachment, message_values, vals = self._get_received_attachment(mes, provider,
                                                                                                 message_values, vals)
                                message_values.update({
                                    'attachment_ids': [(4, attachment.id)],
                                })
                                vals.update({
                                    'attachment_ids': [(4, attachment.id)],
                                })
                            elif mes.get('type') == 'reaction':
                                message_values.update({
                                    'body': mes.get('reaction').get('emoji')
                                })
                                vals.update({
                                    'message': mes.get('reaction').get('emoji')
                                })
                            elif mes.get('type') == 'button':
                                message_values.update({
                                    'body': mes.get('button').get('text')
                                })
                                vals.update({
                                    'message': mes.get('button').get('text')
                                })
                            elif mes.get('type') == 'interactive':
                                if mes.get('interactive').get('type') == 'nfm_reply':
                                    message_values.update({
                                        'body': 'Whatsapp Flow Received'
                                    })
                                    vals.update({
                                        'message': 'Whatsapp Flow Received'
                                    })

                                else:
                                    title = list(
                                        map(lambda l: mes.get('interactive').get(l), mes.get('interactive')))
                                    message_values.update({
                                        'body': len(title) > 0 and title[1].get('title') or '',
                                    })
                                    vals.update({
                                        'message': len(title) > 0 and title[1].get('title') or ''
                                    })
                            else:
                                order_message = ''
                                if mes.get('type', '') == 'order':
                                    order_message += 'Catalog Order Created'
                                message_values.update({
                                    'body': mes.get('text').get('body') if mes.get('text') else order_message
                                })
                                vals.update({
                                    'message': mes.get('text').get('body') if mes.get('text') else order_message
                                })

                            if 'context' in mes or mes.get('reaction', {}).get('message_id', False):
                                parent_message = request.env['mail.message'].sudo().search_read(
                                    [('wa_message_id', '=',
                                      mes.get('context').get('id') if mes.get('context', False) else mes.get(
                                          'reaction').get('message_id'))],
                                    ['id', 'body', 'chatter_wa_model', 'chatter_wa_res_id',
                                     'chatter_wa_message_id'])
                                if len(parent_message) > 0:
                                    message_values.update({'parent_id': parent_message[0]['id'],
                                                           'model': parent_message[0].get('chatter_wa_model') or 'discuss.channel',
                                                           'res_id': parent_message[0].get('chatter_wa_res_id') or channel.id})

                            message = request.env['mail.message'].sudo().with_user(provider.user_id.id).with_context(
                                {'message': 'received'}).create(
                                message_values)
                            channel._broadcast(channel.channel_member_ids.mapped('partner_id').ids)
                            channel._notify_thread(message, message_values)
                            vals.update({'mail_message_id': message.id})
                            request.env['whatsapp.history'].sudo().with_user(provider.user_id.id).with_context(
                                {'message': 'received'}).create(vals)

        return wa_dict

    @http.route(['/send/product'], type='json', methods=['POST'])
    def _send_product_by_whatsapp(self, **kw):
        provider_id = False
        if 'provider_id' in kw and kw.get('provider_id') != '':
            channel_company_line_id = request.env['channel.provider.line'].search(
                [('channel_id', '=', kw.get('provider_id'))])
            if channel_company_line_id.provider_id:
                provider_id = channel_company_line_id.provider_id

        # image = kw.get('image').split(',')[1]
        Attachment = request.env['ir.attachment']
        partner_id = request.env['res.partner'].sudo().browse(int(kw.get('partner_id')))
        product = request.env['product.product'].sudo().browse(int(kw.get('product_id')))
        body_message = product.name + "\n" + request.env.user.company_id.currency_id.symbol + " " + str(
            product.list_price) + " / " + product.uom_id.name
        attac_id = False
        if product.image_1920:
            name = product.name + '.png'
            attac_id = request.env['ir.attachment'].sudo().search([('name', '=', name)], limit=1)
            if not attac_id:
                attac_id = Attachment.create({'name': name,
                                              'type': 'binary',
                                              'datas': product.image_1920,
                                              'store_fname': name,
                                              'res_model': 'wa.msgs',
                                              'mimetype': 'image/jpeg',
                                              })
        user_partner = request.env.user.partner_id
        channel = self.get_channel([int(kw.get('partner_id'))], provider_id)

        if channel:
            message_values = {
                'body': body_message,
                'author_id': user_partner.id,
                'email_from': user_partner.email or '',
                'model': 'discuss.channel',
                'message_type': 'wa_msgs',
                'isWaMsgs': True,
                # 'subtype_id': request.env['ir.model.data'].sudo().xmlid_to_res_id('mail.mt_comment'),
                'subtype_id': request.env['ir.model.data'].sudo()._xmlid_to_res_id('mail.mt_comment'),
                # 'channel_ids': [(4, channel.id)],
                'partner_ids': [(4, user_partner.id)],
                'res_id': channel.id,
                'reply_to': user_partner.email,
                # 'company_id': kw.get('company_id'),
            }
            if attac_id:
                message_values.update({'attachment_ids': [(4, attac_id.id)]})
        return True

    def slicedict(self, d, s):
        return {k: v for k, v in d.items() if k.startswith(s)}

    def filter_json_nfm(self, json_nfm):
        screens = self.slicedict(json_nfm, 'screen_')
        screen_list = {}
        for key, value in screens.items():
            split_key = key.split('_')
            if split_key[0] + '_' + split_key[1] in screen_list.keys():
                screen_list[split_key[0] + '_' + split_key[1]].update({
                    split_key[2] + '_' + split_key[3]: value
                })
            else:
                screen_list[split_key[0] + '_' + split_key[1]] = {
                    split_key[2] + '_' + split_key[3]: value
                }
        return screen_list
