from odoo import _, api, fields, models, modules, tools, Command
import json
from collections import defaultdict
from odoo.tools.misc import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.addons.mail.models.discuss.discuss_channel import Channel
from odoo.addons.mail.tools.discuss import Store
from datetime import timedelta
from odoo.osv import expression
from markupsafe import Markup
from odoo.exceptions import ValidationError


def _to_store(self, store: Store):

        """ Get the information header for the current channels
            :returns a list of updated channels values
            :rtype : list(dict)
        """
        if not self:
            return []
        # sudo: bus.bus: reading non-sensitive last id
        bus_last_id = self.env["bus.bus"].sudo()._bus_last_id()
        current_partner, current_guest = self.env["res.partner"]._get_current_persona()
        self.env['discuss.channel'].flush_model()
        self.env['discuss.channel.member'].flush_model()
        # Query instead of ORM for performance reasons: "LEFT JOIN" is more
        # efficient than "id IN" for the cross-table condition between channel
        # (for channel_type) and member (for other fields).
        self.env.cr.execute("""
                 SELECT discuss_channel_member.id
                   FROM discuss_channel_member
              LEFT JOIN discuss_channel
                     ON discuss_channel.id = discuss_channel_member.channel_id
                    AND discuss_channel.channel_type != 'channel'
                  WHERE discuss_channel_member.channel_id in %(channel_ids)s
                    AND (
                        discuss_channel.id IS NOT NULL
                     OR discuss_channel_member.rtc_inviting_session_id IS NOT NULL
                     OR discuss_channel_member.partner_id = %(current_partner_id)s
                     OR discuss_channel_member.guest_id = %(current_guest_id)s
                    )
               ORDER BY discuss_channel_member.id ASC
        """, {'channel_ids': tuple(self.ids), 'current_partner_id': current_partner.id or None,
              'current_guest_id': current_guest.id or None})
        all_needed_members = self.env['discuss.channel.member'].browse([m['id'] for m in self.env.cr.dictfetchall()])
        all_needed_members._to_store(Store())  # prefetch in batch
        members_by_channel = defaultdict(lambda: self.env['discuss.channel.member'])
        invited_members_by_channel = defaultdict(lambda: self.env['discuss.channel.member'])
        member_of_current_user_by_channel = defaultdict(lambda: self.env['discuss.channel.member'])
        for member in all_needed_members:
            members_by_channel[member.channel_id] += member
            if member.rtc_inviting_session_id:
                invited_members_by_channel[member.channel_id] += member
            if (current_partner and member.partner_id == current_partner) or (
                    current_guest and member.guest_id == current_guest):
                member_of_current_user_by_channel[member.channel_id] = member
        for channel in self:
            member = member_of_current_user_by_channel.get(channel, self.env['discuss.channel.member']).with_prefetch(
                [m.id for m in member_of_current_user_by_channel.values()])
            info = channel._channel_basic_info()
            info["is_editable"] = channel.is_editable
            info["fetchChannelInfoState"] = "fetched"
            custom_channel = ''
            if channel._fields.get('whatsapp_channel'):
                if channel.whatsapp_channel:
                    custom_channel += 'WpChannels'
            if channel._fields.get('instagram_channel'):
                if channel.instagram_channel:
                    custom_channel += 'InstaChannels'
            if channel._fields.get('facebook_channel'):
                if channel.facebook_channel:
                    custom_channel += 'FbChannels'

            if custom_channel:
                info['channel_type'] = custom_channel
            # find the channel member state
            if current_partner or current_guest:
                info['message_needaction_counter'] = channel.message_needaction_counter
                info["message_needaction_counter_bus_id"] = bus_last_id
                if member:
                    store.add(
                        member,
                        extra_fields={
                            "last_interest_dt": True,
                            "message_unread_counter": True,
                            "message_unread_counter_bus_id": bus_last_id,
                            "new_message_separator": True
                        },
                    )
                    info['state'] = member.fold_state or 'closed'
                    info['custom_notifications'] = member.custom_notifications
                    info['mute_until_dt'] = fields.Datetime.to_string(member.mute_until_dt)
                    info['custom_channel_name'] = member.custom_channel_name
                    info['is_pinned'] = member.is_pinned
                    if member.rtc_inviting_session_id:
                        # sudo: discuss.channel.rtc.session - reading sessions of accessible channel is acceptable
                        info["rtcInvitingSession"] = Store.one(member.rtc_inviting_session_id.sudo())
            # add members info
            if channel.channel_type != 'channel':
                # avoid sending potentially a lot of members for big channels
                # exclude chat and other small channels from this optimization because they are
                # assumed to be smaller and it's important to know the member list for them
                store.add(members_by_channel[channel] - member)
            # add RTC sessions info
            invited_members = invited_members_by_channel[channel]
            info["invitedMembers"] = Store.many(
                invited_members, "ADD", fields={"channel": [], "persona": ["name", "im_status"]}
            )
            # sudo: discuss.channel.rtc.session - reading sessions of accessible channel is acceptable
            info["rtcSessions"] = Store.many(channel.sudo().rtc_session_ids, "ADD", extra=True)
            store.add(channel, info)


Channel._to_store = _to_store


class ChannelExtend(models.Model):
    _inherit = 'discuss.channel'

    @api.model
    # @api.returns('self', lambda channel: channel._channel_info()[0])
    @api.returns('self', lambda channels: Store(channels).get_result())
    def channel_get(self, partners_to, pin=True, force_open=False):
        """ Get the canonical private channel between some partners, create it if needed.
            To reuse an old channel (conversation), this one must be private, and contains
            only the given partners.
            :param partners_to : list of res.partner ids to add to the conversation
            :param pin : True if getting the channel should pin it for the current user
            :returns: channel_info of the created or existing channel
            :rtype: dict
        """
        partner_info = False
        if self.env.user.partner_id.id not in partners_to:
            partner_info = self.env['res.partner'].sudo().search([('id', 'in', partners_to)])
            partners_to.append(self.env.user.partner_id.id)
        # determine type according to the number of partner in the channel
        else:
            partner_info = self.env['res.partner'].sudo().search([('id', 'in', partners_to)])
        self.flush_model()
        self.env['discuss.channel.member'].flush_model()
        provider_channel_id = partner_info.channel_provider_line_ids.filtered(lambda s: s.provider_id == self.env.user.provider_id)
        if provider_channel_id and not partner_info.user_ids:
            if not all(x in provider_channel_id.channel_id.channel_partner_ids.ids for x in partners_to):
                provider_channel_id = False
        if not provider_channel_id:
            provider_channel_id = self.env.user.partner_id.channel_provider_line_ids.filtered(lambda s: s.provider_id == self.env.user.provider_id)
            if not all(x in provider_channel_id.channel_id.channel_partner_ids.ids for x in partners_to):
                provider_channel_id = False

        if provider_channel_id and provider_channel_id.provider_id:
            # get the existing channel between the given partners
            channel = self.browse(provider_channel_id.channel_id.filtered(lambda x: x.whatsapp_channel).id)
            if not channel:
                channel |= self.create({
                    'channel_partner_ids': [(4, partner_id) for partner_id in partners_to],
                    'channel_member_ids': [
                        Command.create({
                            'partner_id': partner_id,
                            # only pin for the current user, so the chat does not show up for the correspondent until a message has been sent
                            'is_pinned': partner_id == self.env.user.partner_id.id
                        }) for partner_id in partners_to
                    ],
                    'channel_type': 'chat',
                    # 'email_send': False,
                    'name': partner_info.name,
                })
                channel._broadcast(partners_to)
                return channel

            # pin up the channel for the current partner
            if pin or open:
                member = self.env['discuss.channel.member'].search(
                    [('partner_id', '=', self.env.user.partner_id.id), ('channel_id', '=', channel.id)])
                vals = {'last_interest_dt': fields.Datetime.now()}
                if pin:
                    vals['unpin_dt'] = False
                if force_open:
                    vals['fold_state'] = "open"
                member.write(vals)

            channel._broadcast(self.env.user.partner_id.ids)
        else:
            self.env.cr.execute("""
                        SELECT M.channel_id
                        FROM discuss_channel C, discuss_channel_member M
                        WHERE M.channel_id = C.id
                            AND M.partner_id IN %s
                            AND C.channel_type LIKE 'chat'
                            AND NOT EXISTS (
                                SELECT 1
                                FROM discuss_channel_member M2
                                WHERE M2.channel_id = C.id
                                    AND M2.partner_id NOT IN %s
                            )
                        GROUP BY M.channel_id
                        HAVING ARRAY_AGG(DISTINCT M.partner_id ORDER BY M.partner_id) = %s
                        LIMIT 1
                    """, (tuple(partners_to), tuple(partners_to), sorted(list(partners_to)),))
            result = self.env.cr.dictfetchall()
            if result:
                # get the existing channel between the given partners
                channel = self.browse(result[0].get('channel_id'))
                # pin up the channel for the current partner
                if pin:
                    self.env['discuss.channel.member'].search(
                        [('partner_id', '=', self.env.user.partner_id.id), ('channel_id', '=', channel.id)]).write({
                        'is_pinned': True,
                        'last_interest_dt': fields.Datetime.now(),
                    })
                channel._broadcast(self.env.user.partner_id.ids)
                return channel
            else:
            # create a new one
                channel = self.create({
                    'channel_member_ids': [
                        Command.create({
                            'partner_id': partner_id,
                            # only pin for the current user, so the chat does not show up for the correspondent until a message has been sent
                            # manually set the last_interest_dt to make sure that it works well with the default last_interest_dt (datetime.now())
                            'unpin_dt': False if partner_id == self.env.user.partner_id.id else fields.Datetime.now(),
                            'last_interest_dt': fields.Datetime.now() if partner_id == self.env.user.partner_id.id else fields.Datetime.now() - timedelta(
                                seconds=30),
                        }) for partner_id in partners_to
                    ],
                    'channel_type': 'chat',
                    'name': ', '.join(self.env['res.partner'].browse(partners_to).mapped('name')),
                })
                have_user = self.env['res.users'].search([('partner_id', 'in', partner_info.ids)])
                if not have_user:
                    channel.whatsapp_channel = True
                if partner_info:
                    # partner_info.channel_id = channel.id
                    partner_info.write({'channel_provider_line_ids': [
                        (0, 0, {'channel_id': channel.id, 'provider_id': self.env.user.provider_id.id})]})
                mail_channel_partner = self.env['discuss.channel.member'].sudo().search(
                    [('channel_id', '=', channel.id), ('partner_id', '=', self.env.user.partner_id.id)])
                mail_channel_partner.write({'is_pinned': True})
                channel._broadcast(partners_to)
            return channel

    def get_channel_agent(self, channel_id):
        if self.env.user:
            channel = self.env['discuss.channel'].sudo().browse(int(channel_id))
            partner_lst = channel.channel_partner_ids.ids
            channel_users = self.env['res.users'].sudo().search_read([('partner_id.id', 'in', partner_lst)],
                                                                     ['id', 'name'])
            users = self.env['res.users'].sudo().search([('partner_id.id', 'not in', partner_lst)])
            users_lst = []
            for user in users:
                if user.has_group('all_in_one_whatsapp_odoo_community.whatsapp_group_user') and user.provider_id and user.provider_id == self.env.user.provider_id:
                    users_lst.append({'name': user.name, 'id': user.id})
            dict = {'channel_users': channel_users, 'users': users_lst}
            return dict

    # def add_agent(self, user_id, channel_id):
    #     user = self.env['res.users'].sudo().browse(int(user_id))
    #     channel = self.env['discuss.channel'].sudo().browse(int(channel_id))
    #     if channel.whatsapp_channel:
    #         channel.write({'channel_partner_ids': [(4, user.partner_id.id)]})
    #         mail_channel_partner = self.env['discuss.channel.member'].sudo().search(
    #             [('channel_id', '=', channel_id),
    #              ('partner_id', '=', user.partner_id.id)])
    #         mail_channel_partner.write({'is_pinned': True})
    #         return True

    def remove_agent(self, user_id, channel_id):
        user = self.env['res.users'].sudo().browse(int(user_id))
        channel = self.env['discuss.channel'].sudo().browse(int(channel_id))
        if channel.whatsapp_channel:
            channel.write({'channel_partner_ids': [(3, user.partner_id.id)]})
            return True

    # @api.constrains('channel_member_ids', 'channel_partner_ids')
    # def _constraint_partners_chat(self):
    #     pass

    def add_members(self, partner_ids=None, guest_ids=None, invite_to_rtc_call=False, open_chat_window=False,
                    post_joined_message=True):
        """ Adds the given partner_ids and guest_ids as member of self channels. """
        current_partner, current_guest = self.env["res.partner"]._get_current_persona()
        partners = self.env['res.partner'].browse(partner_ids or []).exists()
        guests = self.env['mail.guest'].browse(guest_ids or []).exists()
        all_new_members = self.env["discuss.channel.member"]
        for channel in self:
            members_to_create = []
            existing_members = self.env['discuss.channel.member'].search(expression.AND([
                [('channel_id', '=', channel.id)],
                expression.OR([
                    [('partner_id', 'in', partners.ids)],
                    [('guest_id', 'in', guests.ids)]
                ])
            ]))
            members_to_create += [{
                'partner_id': partner.id,
                'channel_id': channel.id,
            } for partner in partners - existing_members.partner_id]
            members_to_create += [{
                'guest_id': guest.id,
                'channel_id': channel.id,
            } for guest in guests - existing_members.guest_id]
            new_members = self.env['discuss.channel.member'].create(members_to_create)
            all_new_members += new_members
            for member in new_members:
                payload = {
                    "channel": {
                        **member.channel_id._channel_basic_info(),
                        "model": "discuss.channel",
                        "is_pinned": True,
                    },
                    "open_chat_window": open_chat_window,
                }
                if not member.is_self and not self.env.user._is_public():
                    payload["invited_by_user_id"] = self.env.user.id
                member._bus_send("discuss.channel/joined", payload)
                if post_joined_message:
                    notification = (
                        _("joined the channel")
                        if member.is_self
                        else _("invited %s to the channel", member._get_html_link(for_persona=True))
                    )
                    member.channel_id.message_post(
                        body=Markup('<div class="o_mail_notification">%s</div>') % notification,
                        message_type="notification",
                        subtype_xmlid="mail.mt_comment",
                    )
            if new_members:
                channel._bus_send_store(
                    Store(channel, {"memberCount": channel.member_count}).add(new_members)
                )
            if existing_members and (current_partner or current_guest):
                # If the current user invited these members but they are already present, notify the current user about their existence as well.
                # In particular this fixes issues where the current user is not aware of its own member in the following case:
                # create channel from form view, and then join from discuss without refreshing the page.
                (current_partner or current_guest)._bus_send_store(
                    Store(channel, {"memberCount": channel.member_count}).add(existing_members)
                )
        if invite_to_rtc_call:
            for channel in self:
                current_channel_member = self.env['discuss.channel.member'].search(
                    [('channel_id', '=', channel.id), ('is_self', '=', True)])
                # sudo: discuss.channel.rtc.session - reading rtc sessions of current user
                if current_channel_member and current_channel_member.sudo().rtc_session_ids:
                    # sudo: discuss.channel.rtc.session - current user can invite new members in call
                    current_channel_member.sudo()._rtc_invite_members(member_ids=new_members.ids)
        return all_new_members




    def action_open_whatapp_channel(self):
        """ Adds the current partner as a member of self channel and pins them if not already pinned. """
        self.ensure_one()
        if self.channel_type != 'chat':
            raise ValidationError(_('This join method is not possible for regular channels.'))

        self.check_access_rights('write')
        self.check_access_rule('write')
        current_partner = self.env.user.partner_id
        member = self.channel_member_ids.filtered(lambda m: m.partner_id == current_partner)
        if member:
            if not member.is_pinned:
                member.write({'is_pinned': True})
        else:
            new_member = self.env['discuss.channel.member'].with_context(
                tools.clean_context(self.env.context)).sudo().create([{
                'partner_id': current_partner.id,
                'channel_id': self.id,
            }])
            message_body = Markup(f'<div class="o_mail_notification">{_("joined the channel")}</div>')
            new_member.channel_id.message_post(body=message_body, message_type="notification",
                                               subtype_xmlid="mail.mt_comment")
            self.env['bus.bus']._sendone(self, 'mail.record/insert', {
                'Thread': {
                    'channelMembers': [('ADD', list(new_member._discuss_channel_member_format().values()))],
                    'id': self.id,
                    'memberCount': self.member_count,
                    'model': "discuss.channel",
                }
            })
        return self._channel_info()[0]

    def channel_fetched(self):
        """ Broadcast the channel_fetched notification to channel members
        """
        for channel in self:
            if not channel.message_ids.ids:
                continue
            # a bit not-modular but helps understanding code
            if channel.channel_type not in {'chat', 'whatsapp'}:
                continue
            last_message_id = channel.message_ids.ids[0] # zero is the index of the last message
            member = self.env['discuss.channel.member'].search([('channel_id', '=', channel.id), ('partner_id', '=', self.env.user.partner_id.id)], limit=1)
            if not member:
                # member not a part of the channel
                continue
            if member.fetched_message_id.id == last_message_id:
                # last message fetched by user is already up-to-date
                return
            # Avoid serialization error when multiple tabs are opened.
            query = """
                UPDATE discuss_channel_member
                SET fetched_message_id = %s
                WHERE id IN (
                    SELECT id FROM discuss_channel_member WHERE id = %s
                    FOR NO KEY UPDATE SKIP LOCKED
                )
            """
            if not member.is_pinned:
                self.env.cr.execute(query, (last_message_id, member.id))
                channel._bus_send(
                    "discuss.channel.member/fetched",
                    {
                        "channel_id": channel.id,
                        "id": member.id,
                        "last_message_id": last_message_id,
                        "partner_id": self.env.user.partner_id.id,
                    },
            )


class ChannelMemberWa(models.Model):
    _inherit = 'discuss.channel.member'

    def _set_last_seen_message(self, message, notify=True):
        """
        Set the last seen message of the current member.

        :param message: the message to set as last seen message.
        :param notify: whether to send a bus notification relative to the new
            last seen message.
        """
        self.ensure_one()
        if self.seen_message_id.id >= message.id:
            return
        self.fetched_message_id = max(self.fetched_message_id.id, message.id)
        self.seen_message_id = message.id
        self.last_seen_dt = fields.Datetime.now()
        if not notify:
            return
        message.write({'isWaMsgsRead': True})
        if message.isWaMsgsRead == True:
            channel_company_line_id = self.env['channel.provider.line'].search(
                [('channel_id', '=', message.res_id)])
            if channel_company_line_id.provider_id:
                provider_id = channel_company_line_id.provider_id
                if provider_id:
                    message_history = self.env['whatsapp.history'].search([('mail_message_id', '=', message.id)])
                    message_id = message.wa_message_id if message.wa_message_id else message_history.message_id
                    answer = provider_id.graph_api_wamsg_mark_as_read(message_id)
                    if answer.status_code == 200:
                        dict = json.loads(answer.text)
                        if provider_id.provider == 'graph_api':  # if condition for Graph API
                            if 'success' in dict and dict.get('success'):
                                message.write({'isWaMsgsRead': True})
                    else:
                        domain = ["&", ("model", "=", "discuss.channel"), ("res_id", "in", self.ids),
                                  ("isWaMsgsRead", "=", False)]
                        if message:
                            domain = expression.AND([domain, [('id', '<=', int(message))]])
                        messages = self.env['mail.message'].search(domain, order="id DESC")
                        final_messages = messages.filtered(lambda x: message.partner_ids.id in x.author_id.ids)
                        for val in final_messages:
                            val_message_id = val.wa_message_id
                            answer = provider_id.graph_api_wamsg_mark_as_read(val_message_id)
                            if answer.status_code == 200:
                                dict = json.loads(answer.text)
                                if provider_id.provider == 'graph_api':  # if condition for Graph API
                                    if 'success' in dict and dict.get('success'):
                                        val.write({'isWaMsgsRead': True})
        target = self
        if self.channel_id.channel_type in self.channel_id._types_allowing_seen_infos():
            target = self.channel_id
        target._bus_send_store(
            self, fields={"channel": [], "persona": ["name"], "seen_message_id": True}
        )