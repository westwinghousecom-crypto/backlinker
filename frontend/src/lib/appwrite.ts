import { Account, AppwriteException, Client, ID } from "appwrite";
import { APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID } from "@/lib/config";

// Browser-side Appwrite client. Used for sign-up / sign-in / sign-out only.
const client = new Client()
  .setEndpoint(APPWRITE_ENDPOINT)
  .setProject(APPWRITE_PROJECT_ID);

export const account = new Account(client);
export { AppwriteException, ID };
