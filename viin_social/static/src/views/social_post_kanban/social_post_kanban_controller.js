/** @odoo-module */

import { useService } from "@web/core/utils/hooks";
import { KanbanController } from "@web/views/kanban/kanban_controller";

export class SocialPostKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.orm = useService("orm");
    }

    async synchAllPosts() {
        this.orm.call("social.post", "action_synchronize_all_post", []).then(function () {
            location.reload();
        });
    }
}
