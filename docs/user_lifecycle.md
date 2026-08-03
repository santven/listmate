# User Lifecycle & Household Status

This document illustrates the lifecycle of a user's household, including Early Adopters, Free Trials, Premium Upgrades, Downgrades, and Secondary Member Spin-offs.

## Lifecycle Flowchart

```mermaid
flowchart TD
    %% Base Entry
    Start([New User Signs Up]) --> CreateHH[Creates New Household]
    CreateHH --> CheckEarly{Household ID <= 25?}
    
    %% Scenario 1: Early Adopter
    CheckEarly -- "Yes" --> EarlyAdopter["Early Adopter Status\n(Premium forever, no billing)"]
    EarlyAdopter --> EAPremium["Full Premium Access & Sync"]
    EAPremium --> EAAddMember["Adds Secondary Member"]
    EAAddMember --> EAPremium
    
    %% Scenarios 2 & 3: Post-25 User
    CheckEarly -- "No" --> FreeTrial["7-Day Free Trial\n(is_premium=true, sub_status='trial')"]
    
    FreeTrial --> TrialUsage["Full Premium Access & Sync"]
    TrialUsage --> AddMember["Adds Secondary Member"]
    AddMember --> TrialEnd{"Trial Expires"}
    
    %% Scenario 2: Upgrade & Renew
    TrialEnd -- "Upgrades before expiry" --> PremiumUser["Premium Status\n(is_premium=true, sub_status='active')"]
    PremiumUser --> PremiumUsage["Full Premium Access & Sync"]
    PremiumUsage --> Renews{"Subscription Renews?"}
    Renews -- "Yes" --> PremiumUsage
    
    %% Scenario 3: Downgrade & Spin-off
    TrialEnd -- "Expires (No Upgrade)" --> Downgrade
    Renews -- "Cancels / Payment Fails" --> Downgrade
    
    Downgrade["Downgraded to Free\n(is_premium=false, downgraded_at=NOW)"] --> FreeRestrictions
    
    FreeRestrictions["Restrictions Applied:\n- Recipe generation locked\n- Secondary Members: Read-Only\n- Owner: Sync paused"]
    
    FreeRestrictions --> SecondaryMemberAction{"Secondary Member Action"}
    SecondaryMemberAction -- "Stays in HH" --> ReadOnly["Read-Only Access to HH"]
    SecondaryMemberAction -- "Chooses to Spin Off" --> SpinOff["Spin Off to New Household\n(Gets new HH ID)"]
    
    SpinOff --> MigrateData["Migrates Stores, Items, Recipes\n(Only those created BEFORE downgraded_at)"]
    MigrateData --> NewFreeHH["New Personal Household\n(Free Tier)"]
    
    FreeRestrictions --> OwnerAction{"Owner Action"}
    OwnerAction -- "Upgrades/Restores" --> PremiumUser
    OwnerAction -- "Stays Free" --> FreeUsage["Local usage, no live sync for members"]
```

## Explanation of Scenarios

1. **Early Adopter**: The first 25 households get `is_early_adopter` flag via ID checks. They always get Premium features, and secondary members always have sync.
2. **Standard Premium & Renewal**: After household 25, users get a trial. If they upgrade, they maintain `is_premium = true`. Secondary members get live sync. 
3. **Downgrade & Spin-Off**: If a standard user's trial or premium expires, `is_premium` becomes `false` and a timestamp `downgraded_at` is set. Secondary members become **Read-Only**. To regain edit access, a secondary member can "Spin Off" to a new personal household. The app migrates items they had access to **before** the `downgraded_at` timestamp so that they don't get data created by the owner while the secondary member was read-only.
