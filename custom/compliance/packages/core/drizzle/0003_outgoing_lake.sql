ALTER TABLE "person_role" DROP CONSTRAINT "person_role_key";--> statement-breakpoint
ALTER TABLE "person_role" ADD COLUMN "slot" text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE "person_role" ADD CONSTRAINT "person_role_key" UNIQUE("cycle_id","role","department_slug","level","slot","region","majlis");