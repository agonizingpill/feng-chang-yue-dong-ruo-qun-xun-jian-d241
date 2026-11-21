export const ROLES={admin:'蜂场主管',beekeeper:'巡箱蜂师',viewer:'观察员'};
export const CARE_KINDS={feed:'饲喂',requeen:'换王'};
export const CARE_STATES={cancelled:'已取消退料',planned:'待执行',executed:'已执行待复查',rechecked:'复查待关闭',needs_requeen:'无王须换王',closed:'越冬复查已关闭'};
export const VISIT_STATES={recorded:'待筛查',screening:'筛查中',screened:'已筛查',caring:'处置中',followup:'已复查',needs_requeen:'须换王',closed:'已闭环',stale:'历史旧巡检',blocked:'待重试'};
export const HIVE_STATES={observe:'常规观察',needs_care:'需要关注',caring:'处置中',needs_requeen:'待换王',winter_ready:'越冬复查通过'};
export const BATCH_STATES={claimed:'已领批待补录',received:'已交接待封存',sealed:'已封存',cancelled:'已取消'};
export const READING_STATES={complete:'完整读数',accepted:'完整读数',incomplete:'缺项待补',conflict:'冲突证据',superseded:'已更正'};
export const BATCH_SCREEN_STATES={idle:'未筛查',queued:'筛查排队中',running:'筛查中',done:'已按封存读数筛查',failed:'筛查失败可重试'};
