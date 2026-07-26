export interface GitHubConfig {
  owner: string;
  repo: string;
  patMasked: string;
  hasKey: boolean;
}

export interface GitHubIssue {
  id: number;
  number: number;
  title: string;
  body: string;
  html_url: string;
  user: {
    login: string;
    avatar_url: string;
  };
  created_at: string;
  labels: { name: string; color: string }[];
}

export interface GitHubBranch {
  name: string;
  commit: {
    sha: string;
    url: string;
  };
  protected: boolean;
}

export interface GitHubPR {
  id: number;
  number: number;
  title: string;
  body: string;
  html_url: string;
  state: "open" | "closed" | "merged";
  draft: boolean;
  user: {
    login: string;
    avatar_url: string;
  };
  head: {
    ref: string;
    label: string;
  };
  base: {
    ref: string;
    label: string;
  };
  created_at: string;
  updated_at: string;
  merged_at: string | null;
}

export interface CommitMessage {
  sha: string;
  message: string;
  author: string;
  date: string;
}

export interface GeneratedReleaseNotes {
  githubNotes: string;
  appStoreNotes: string;
}

export interface GroceryItem {
  id: string;
  name: string;
  category: string;
  quantity: number;
  unit: string;
  isPurchased: boolean;
  priceEstimated: number;
  notes?: string;
  addedAt: string;
}

export interface GroceryCategory {
  name: string;
  icon: string;
  color: string;
}

export interface MealPlanIngredientsResponse {
  dish: string;
  servings: number;
  ingredients: {
    name: string;
    category: string;
    quantity: number;
    unit: string;
    priceEstimated: number;
    notes?: string;
  }[];
}

