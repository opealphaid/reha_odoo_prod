/** @odoo-module */

import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { SocialNoticeListController as Controller } from "./social_notice_list_controller";

export const SocialNoticeListView = {
    ...listView,
    Controller,
    buttonTemplate: "viin_social.SoicalNoticeListView.Buttons",
};

registry.category("views").add("social_notice_list", SocialNoticeListView);
