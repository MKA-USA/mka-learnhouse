CREATE TABLE "dashboard_access_override" (
	"id" serial PRIMARY KEY NOT NULL,
	"email" text NOT NULL,
	"scope_type" text NOT NULL,
	"scope_value" text DEFAULT '' NOT NULL,
	"reason" text,
	"created_by" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "dashboard_access_override_key" UNIQUE("email","scope_type","scope_value")
);
--> statement-breakpoint
CREATE TABLE "progress_snapshot" (
	"id" serial PRIMARY KEY NOT NULL,
	"cycle_id" integer NOT NULL,
	"snapshot_date" date NOT NULL,
	"roster_key" text NOT NULL,
	"department_slug" text DEFAULT '' NOT NULL,
	"level" text NOT NULL,
	"region" text DEFAULT '' NOT NULL,
	"majlis" text DEFAULT '' NOT NULL,
	"role_title" text DEFAULT '' NOT NULL,
	"learner_email" text NOT NULL,
	"person_name" text,
	"appointed_on" date,
	"due_on" date NOT NULL,
	"stage" text NOT NULL,
	"status" text NOT NULL,
	"overdue" boolean DEFAULT false NOT NULL,
	"days_overdue" integer DEFAULT 0 NOT NULL,
	"lessons_done" integer DEFAULT 0 NOT NULL,
	"lessons_total" integer DEFAULT 0 NOT NULL,
	"quiz_avg" integer,
	"completed_at" date,
	"attested_at" date,
	"last_activity_at" date,
	"expected_attested" real DEFAULT 0 NOT NULL,
	"self_check_answered" boolean DEFAULT false NOT NULL,
	"self_check_mismatches" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "progress_snapshot_key" UNIQUE("cycle_id","snapshot_date","roster_key")
);
--> statement-breakpoint
CREATE TABLE "snapshot_run" (
	"id" serial PRIMARY KEY NOT NULL,
	"cycle_id" integer NOT NULL,
	"snapshot_date" date NOT NULL,
	"source" text NOT NULL,
	"status" text NOT NULL,
	"learners" integer DEFAULT 0 NOT NULL,
	"errors" integer DEFAULT 0 NOT NULL,
	"note" text,
	"started_at" timestamp with time zone DEFAULT now() NOT NULL,
	"finished_at" timestamp with time zone
);
--> statement-breakpoint
ALTER TABLE "progress_snapshot" ADD CONSTRAINT "progress_snapshot_cycle_id_cycle_id_fk" FOREIGN KEY ("cycle_id") REFERENCES "public"."cycle"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "snapshot_run" ADD CONSTRAINT "snapshot_run_cycle_id_cycle_id_fk" FOREIGN KEY ("cycle_id") REFERENCES "public"."cycle"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "progress_snapshot_dept_idx" ON "progress_snapshot" USING btree ("cycle_id","snapshot_date","department_slug");--> statement-breakpoint
CREATE INDEX "progress_snapshot_region_idx" ON "progress_snapshot" USING btree ("cycle_id","snapshot_date","region");--> statement-breakpoint
CREATE INDEX "snapshot_run_date_idx" ON "snapshot_run" USING btree ("cycle_id","snapshot_date");