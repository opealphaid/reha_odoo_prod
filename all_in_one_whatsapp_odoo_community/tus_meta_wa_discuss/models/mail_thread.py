from odoo import _, api, fields, models, modules, tools

class Thread(models.AbstractModel):
    _inherit = 'mail.thread'

    # def _notify_thread(self, message, msg_vals=False, **kwargs):
    #     if msg_vals.get('message_type') == 'wa_msgs':
    #         self = self._fallback_lang()

    #         msg_vals = msg_vals if msg_vals else {}
    #         recipients_data = self._notify_get_recipients(message, msg_vals, **kwargs)
    #         return []
    #     recipients_data = super()._notify_thread(message, msg_vals=msg_vals, **kwargs)
    #     return recipients_data

    def _get_mail_thread_data(self, request_list):
        res = super(Thread, self)._get_mail_thread_data(request_list)
        not_send_msgs_btn_in_chatter = []
        not_wa_msgs_btn_in_chatter = []

        if res.get('followers', False) and res.get('followers')[0]:
            # if res.get('followers')[0].get('partner', False) and res.get('followers')[0].get('partner', False)[
            #     'not_send_msgs_btn_in_chatter']:
            not_send_msgs_btn_in_chatter += [i['model'] for i in res.get('followers')[0].get('partner', False)['not_send_msgs_btn_in_chatter']]
            not_wa_msgs_btn_in_chatter += [i['model'] for i in res.get('followers')[0].get('partner', False)['not_wa_msgs_btn_in_chatter']]

        res['not_send_msgs_btn_in_chatter'] = not_send_msgs_btn_in_chatter
        res['not_wa_msgs_btn_in_chatter'] = not_wa_msgs_btn_in_chatter
        return res

    def get_template_req_val(self, res_id, res_model):
        send_template_req = True
        record = self.env[res_model].browse(res_id)
        if res_model != 'discuss.channel':
            if res_model == 'res.partner':
                send_template_req = record.send_template_req
            else:
                if hasattr(self.env[res_model],'partner_id') and record.partner_id:
                    send_template_req = record.partner_id.send_template_req

        return send_template_req
