CREATE TABLE "cycle" (
	"id" serial PRIMARY KEY NOT NULL,
	"label" text NOT NULL,
	"starts_on" date NOT NULL,
	"deadline_on" date NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "cycle_label_unique" UNIQUE("label")
);
--> statement-breakpoint
CREATE TABLE "department" (
	"slug" text PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"translation" text NOT NULL,
	"mailbox_prefix" text NOT NULL,
	"level_scope" text[] DEFAULT '{"national","region","majlis"}' NOT NULL,
	"sort_order" integer DEFAULT 0 NOT NULL,
	"rules_version" text DEFAULT '2026.1' NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "person_role" (
	"id" serial PRIMARY KEY NOT NULL,
	"cycle_id" integer NOT NULL,
	"department_slug" text NOT NULL,
	"level" text NOT NULL,
	"region" text DEFAULT '' NOT NULL,
	"majlis" text DEFAULT '' NOT NULL,
	"role_title" text DEFAULT '' NOT NULL,
	"learner_email" text NOT NULL,
	"person_name" text,
	"appointed_on" text,
	"source" text DEFAULT 'formula' NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "person_role_key" UNIQUE("cycle_id","department_slug","level","region","majlis")
);
--> statement-breakpoint
CREATE TABLE "dept_plan" (
	"id" serial PRIMARY KEY NOT NULL,
	"cycle_id" integer NOT NULL,
	"department_slug" text NOT NULL,
	"level" text NOT NULL,
	"responsibilities_md" text DEFAULT '' NOT NULL,
	"okrs_md" text DEFAULT '' NOT NULL,
	"resources_md" text DEFAULT '' NOT NULL,
	"stale" boolean DEFAULT false NOT NULL,
	"updated_by" text,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "dept_plan_key" UNIQUE("cycle_id","department_slug","level")
);
--> statement-breakpoint
CREATE TABLE "directory_override" (
	"id" serial PRIMARY KEY NOT NULL,
	"cycle_id" integer NOT NULL,
	"department_slug" text NOT NULL,
	"level" text NOT NULL,
	"region" text DEFAULT '' NOT NULL,
	"majlis" text DEFAULT '' NOT NULL,
	"learner_email" text,
	"person_name" text,
	"note" text,
	"created_by" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "directory_override_key" UNIQUE("cycle_id","department_slug","level","region","majlis")
);
--> statement-breakpoint
CREATE TABLE "course_map" (
	"id" serial PRIMARY KEY NOT NULL,
	"cycle_id" integer NOT NULL,
	"kind" text NOT NULL,
	"department_slug" text DEFAULT '' NOT NULL,
	"lh_course_uuid" text NOT NULL,
	"lh_course_id" integer,
	"structure" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"content_hash" text,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "course_map_key" UNIQUE("cycle_id","kind","department_slug"),
	CONSTRAINT "course_map_uuid" UNIQUE("lh_course_uuid")
);
--> statement-breakpoint
CREATE TABLE "idmap" (
	"id" serial PRIMARY KEY NOT NULL,
	"source_system" text NOT NULL,
	"source_kind" text NOT NULL,
	"source_id" text NOT NULL,
	"lh_kind" text NOT NULL,
	"lh_uuid" text NOT NULL,
	"source_path" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "idmap_key" UNIQUE("source_system","source_kind","source_id")
);
--> statement-breakpoint
CREATE TABLE "enrollment_log" (
	"id" serial PRIMARY KEY NOT NULL,
	"cycle_id" integer NOT NULL,
	"lh_course_uuid" text NOT NULL,
	"learner_email" text NOT NULL,
	"lh_user_id" integer,
	"status" text DEFAULT 'planned' NOT NULL,
	"detail" text,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "enrollment_log_key" UNIQUE("cycle_id","lh_course_uuid","learner_email")
);
--> statement-breakpoint
ALTER TABLE "person_role" ADD CONSTRAINT "person_role_cycle_id_cycle_id_fk" FOREIGN KEY ("cycle_id") REFERENCES "public"."cycle"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "person_role" ADD CONSTRAINT "person_role_department_slug_department_slug_fk" FOREIGN KEY ("department_slug") REFERENCES "public"."department"("slug") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "dept_plan" ADD CONSTRAINT "dept_plan_cycle_id_cycle_id_fk" FOREIGN KEY ("cycle_id") REFERENCES "public"."cycle"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "dept_plan" ADD CONSTRAINT "dept_plan_department_slug_department_slug_fk" FOREIGN KEY ("department_slug") REFERENCES "public"."department"("slug") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "directory_override" ADD CONSTRAINT "directory_override_cycle_id_cycle_id_fk" FOREIGN KEY ("cycle_id") REFERENCES "public"."cycle"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "directory_override" ADD CONSTRAINT "directory_override_department_slug_department_slug_fk" FOREIGN KEY ("department_slug") REFERENCES "public"."department"("slug") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "course_map" ADD CONSTRAINT "course_map_cycle_id_cycle_id_fk" FOREIGN KEY ("cycle_id") REFERENCES "public"."cycle"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "enrollment_log" ADD CONSTRAINT "enrollment_log_cycle_id_cycle_id_fk" FOREIGN KEY ("cycle_id") REFERENCES "public"."cycle"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "person_role_email_idx" ON "person_role" USING btree ("cycle_id","learner_email");