CREATE TABLE `argument_lines` (
	`item_id` text PRIMARY KEY NOT NULL,
	`act` text NOT NULL,
	`hook` text DEFAULT '' NOT NULL,
	`claim` text DEFAULT '' NOT NULL,
	`by` text DEFAULT 'Alpha' NOT NULL,
	`at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `decisions` (
	`id` text PRIMARY KEY NOT NULL,
	`kind` text DEFAULT 'post' NOT NULL,
	`status` text NOT NULL,
	`note` text DEFAULT '' NOT NULL,
	`by` text DEFAULT 'Alpha' NOT NULL,
	`at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `edits` (
	`item_id` text PRIMARY KEY NOT NULL,
	`title` text DEFAULT '' NOT NULL,
	`post` text DEFAULT '' NOT NULL,
	`teaser_linkedin` text DEFAULT '' NOT NULL,
	`teaser_x` text DEFAULT '' NOT NULL,
	`base_hash` text NOT NULL,
	`by` text DEFAULT 'Alpha' NOT NULL,
	`at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `findings` (
	`id` text PRIMARY KEY NOT NULL,
	`theme` text DEFAULT '' NOT NULL,
	`summary` text DEFAULT '' NOT NULL,
	`why` text DEFAULT '' NOT NULL,
	`shape` text DEFAULT '' NOT NULL,
	`relevance` text DEFAULT '' NOT NULL,
	`sentiment` text DEFAULT '' NOT NULL,
	`source` text DEFAULT '' NOT NULL,
	`url` text DEFAULT '' NOT NULL,
	`at` text,
	`status` text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE TABLE `inventory` (
	`rowid` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`scope` text DEFAULT '' NOT NULL,
	`brand` text DEFAULT '' NOT NULL,
	`name` text DEFAULT '' NOT NULL,
	`platform` text DEFAULT '' NOT NULL,
	`handle` text DEFAULT '' NOT NULL,
	`status` text DEFAULT '' NOT NULL,
	`last_verified` text,
	`stale` integer DEFAULT false NOT NULL,
	`note` text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE TABLE `items` (
	`id` text PRIMARY KEY NOT NULL,
	`title` text DEFAULT '' NOT NULL,
	`theme` text DEFAULT '' NOT NULL,
	`stream` text DEFAULT '' NOT NULL,
	`type` text DEFAULT '' NOT NULL,
	`pillar` text DEFAULT '' NOT NULL,
	`platform` text DEFAULT '' NOT NULL,
	`format` text DEFAULT '' NOT NULL,
	`owner` text DEFAULT '' NOT NULL,
	`campaign` text DEFAULT '' NOT NULL,
	`date` text,
	`status` text DEFAULT 'Idea' NOT NULL,
	`alpha_status` text DEFAULT 'proposed' NOT NULL,
	`gate_verdict` text DEFAULT '' NOT NULL,
	`gate` text,
	`logic` text DEFAULT '' NOT NULL,
	`finding_id` text DEFAULT '' NOT NULL,
	`anchor` text DEFAULT '' NOT NULL,
	`slug` text DEFAULT '' NOT NULL,
	`excerpt` text DEFAULT '' NOT NULL,
	`cta` text DEFAULT '' NOT NULL,
	`post` text DEFAULT '' NOT NULL,
	`teaser_linkedin` text DEFAULT '' NOT NULL,
	`teaser_x` text DEFAULT '' NOT NULL,
	`hooks_considered` text,
	`partner_tags` text,
	`freshness_deadline` text,
	`drafted_by` text DEFAULT '' NOT NULL,
	`drafted_at` text,
	`note_hash` text DEFAULT '' NOT NULL,
	`note_path` text DEFAULT '' NOT NULL,
	`desk_edit` text,
	`published_at` text,
	`notion_url` text DEFAULT '' NOT NULL,
	`synced_at` text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE INDEX `items_date_idx` ON `items` (`date`);--> statement-breakpoint
CREATE INDEX `items_theme_idx` ON `items` (`theme`);--> statement-breakpoint
CREATE TABLE `proposals` (
	`id` text PRIMARY KEY NOT NULL,
	`theme` text DEFAULT '' NOT NULL,
	`author` text DEFAULT '' NOT NULL,
	`handle` text DEFAULT '' NOT NULL,
	`platform` text DEFAULT '' NOT NULL,
	`url` text DEFAULT '' NOT NULL,
	`why` text DEFAULT '' NOT NULL,
	`draft` text DEFAULT '' NOT NULL,
	`at` text
);
--> statement-breakpoint
CREATE TABLE `reviews` (
	`rowid` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`item_id` text NOT NULL,
	`kind` text DEFAULT 'post' NOT NULL,
	`theme` text DEFAULT '' NOT NULL,
	`title` text DEFAULT '' NOT NULL,
	`verdict` text DEFAULT '' NOT NULL,
	`rationale` text NOT NULL,
	`scope` text DEFAULT 'item' NOT NULL,
	`by` text DEFAULT 'Alpha' NOT NULL,
	`at` text NOT NULL,
	`synced_at` text
);
--> statement-breakpoint
CREATE INDEX `reviews_item_idx` ON `reviews` (`item_id`);--> statement-breakpoint
CREATE INDEX `reviews_synced_idx` ON `reviews` (`synced_at`);--> statement-breakpoint
CREATE TABLE `runs` (
	`rowid` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`run_id` text DEFAULT '' NOT NULL,
	`step` text DEFAULT '' NOT NULL,
	`at` text,
	`detail` text DEFAULT '' NOT NULL,
	`items` integer,
	`terms` integer,
	`elapsed_s` text,
	`file` text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE TABLE `sync_meta` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE TABLE `themes` (
	`tag` text PRIMARY KEY NOT NULL,
	`differentiator` text DEFAULT '' NOT NULL,
	`licence` text DEFAULT '' NOT NULL,
	`fact` text DEFAULT '' NOT NULL,
	`partners` text
);
