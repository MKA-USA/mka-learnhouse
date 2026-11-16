ALTER TABLE "course_map" DROP CONSTRAINT "course_map_key";--> statement-breakpoint
ALTER TABLE "idmap" DROP CONSTRAINT "idmap_key";--> statement-breakpoint
ALTER TABLE "enrollment_log" DROP CONSTRAINT "enrollment_log_key";--> statement-breakpoint
ALTER TABLE "course_map" ADD COLUMN "target" text DEFAULT 'dev' NOT NULL;--> statement-breakpoint
ALTER TABLE "idmap" ADD COLUMN "target" text DEFAULT 'dev' NOT NULL;--> statement-breakpoint
ALTER TABLE "enrollment_log" ADD COLUMN "target" text DEFAULT 'dev' NOT NULL;--> statement-breakpoint
ALTER TABLE "course_map" ADD CONSTRAINT "course_map_key" UNIQUE("target","cycle_id","kind","department_slug");--> statement-breakpoint
ALTER TABLE "idmap" ADD CONSTRAINT "idmap_key" UNIQUE("target","source_system","source_kind","source_id");--> statement-breakpoint
ALTER TABLE "enrollment_log" ADD CONSTRAINT "enrollment_log_key" UNIQUE("target","cycle_id","lh_course_uuid","learner_email");