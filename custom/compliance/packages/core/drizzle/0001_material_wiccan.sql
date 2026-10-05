ALTER TABLE "person_role" DROP CONSTRAINT "person_role_key";--> statement-breakpoint
ALTER TABLE "person_role" DROP CONSTRAINT "person_role_department_slug_department_slug_fk";
--> statement-breakpoint
ALTER TABLE "person_role" ALTER COLUMN "department_slug" SET DEFAULT '';--> statement-breakpoint
ALTER TABLE "person_role" ADD COLUMN "role" text DEFAULT 'nazim_dept' NOT NULL;--> statement-breakpoint
ALTER TABLE "person_role" ADD CONSTRAINT "person_role_key" UNIQUE("cycle_id","role","department_slug","level","region","majlis");