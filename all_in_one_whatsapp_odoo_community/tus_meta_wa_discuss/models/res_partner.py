# -*- coding: utf-8 -*-
from ast import literal_eval
from dateutil import tz
from datetime import datetime, timedelta
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    send_template_req = fields.Boolean("Send Template Require", default=True)
    
    # def mail_partner_format(self, fields=None):
    #     res = super().mail_partner_format(fields=fields)
    #     for partner in self:
    #         internal_users = partner.user_ids - partner.user_ids.filtered('share')
    #         main_user = internal_users[0] if len(internal_users) > 0 else partner.user_ids[0] if len(
    #             partner.user_ids) > 0 else self.env['res.users']
    #         res[partner].update({"send_template_req": partner.send_template_req})
    #         res[partner].update({"is_whatsapp_user": main_user.has_group('tus_meta_whatsapp_base.whatsapp_group_user')})
    #         res[partner].update({"not_wa_msgs_btn_in_chatter":self.env['ir.model'].search_read([("id","in",literal_eval((self.env['ir.config_parameter'].sudo().get_param('tus_meta_wa_discuss.not_wa_msgs_btn_in_chatter'))))],['id','name','model']) if self.env['ir.config_parameter'].sudo().get_param('tus_meta_wa_discuss.not_wa_msgs_btn_in_chatter') else []})
    #         res[partner].update({"not_send_msgs_btn_in_chatter":self.env['ir.model'].search_read([("id","in",literal_eval((self.env['ir.config_parameter'].sudo().get_param('tus_meta_wa_discuss.not_send_msgs_btn_in_chatter'))))],['id','name','model']) if self.env['ir.config_parameter'].sudo().get_param('tus_meta_wa_discuss.not_send_msgs_btn_in_chatter') else []})
    #     return res
