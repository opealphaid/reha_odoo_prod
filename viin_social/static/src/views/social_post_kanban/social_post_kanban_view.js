/** @odoo-module */

import { kanbanView } from "@web/views/kanban/kanban_view";
import { registry } from "@web/core/registry";
import { SocialPostKanbanController as Controller } from "./social_post_kanban_controller";

export const SocialPostKanbanView = {
    ...kanbanView,
    Controller,
    buttonTemplate: "viin_social.SocialPostKanbanView.Buttons",
};

registry.category("views").add("social_post_kanban", SocialPostKanbanView);
