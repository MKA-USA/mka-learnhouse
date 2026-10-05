ALTER TABLE "directory_override" DROP CONSTRAINT "directory_override_key";--> statement-breakpoint
ALTER TABLE "directory_override" DROP CONSTRAINT "directory_override_department_slug_department_slug_fk";
--> statement-breakpoint
ALTER TABLE "directory_override" ALTER COLUMN "department_slug" SET DEFAULT '';--> statement-breakpoint
ALTER TABLE "dept_plan" ADD COLUMN "responsibilities_doc" jsonb;--> statement-breakpoint
ALTER TABLE "dept_plan" ADD COLUMN "okrs_doc" jsonb;--> statement-breakpoint
ALTER TABLE "dept_plan" ADD COLUMN "resources_doc" jsonb;--> statement-breakpoint
ALTER TABLE "dept_plan" ADD COLUMN "source" text DEFAULT 'csv' NOT NULL;--> statement-breakpoint
ALTER TABLE "directory_override" ADD COLUMN "role" text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE "directory_override" ADD CONSTRAINT "directory_override_key" UNIQUE("cycle_id","department_slug","level","role","region","majlis");