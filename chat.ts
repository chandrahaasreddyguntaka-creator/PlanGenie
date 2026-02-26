@tailwind base;
@tailwind components;
@tailwind utilities;

/* Definition of the design system. All colors, gradients, fonts, etc should be defined here. 
All colors MUST be HSL.
*/

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;

    --card: 0 0% 100%;
    --card-foreground: 222.2 84% 4.9%;

    --popover: 0 0% 100%;
    --popover-foreground: 222.2 84% 4.9%;

    /* Deep navy/dark blue primary colors */
    --primary: 220 90% 28%;
    --primary-foreground: 0 0% 100%;
    
    --secondary: 220 85% 35%;
    --secondary-foreground: 0 0% 100%;

    --muted: 220 20% 96%;
    --muted-foreground: 220 10% 50%;

    --accent: 220 90% 32%;
    --accent-foreground: 0 0% 100%;

    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;

    --border: 220 20% 90%;
    --input: 220 20% 90%;
    --ring: 220 90% 28%;

    --radius: 0.5rem;

    /* Navy gradients */
    --gradient-primary: linear-gradient(135deg, hsl(220 90% 28%), hsl(220 85% 35%));
    --gradient-subtle: linear-gradient(180deg, hsl(0 0% 100%), hsl(220 20% 98%));

    --sidebar-background: 220 20% 98%;
    --sidebar-foreground: 220 20% 20%;
    --sidebar-primary: 220 90% 28%;
    --sidebar-primary-foreground: 0 0% 100%;
    --sidebar-accent: 220 90% 95%;
    --sidebar-accent-foreground: 220 90% 28%;
    --sidebar-border: 220 20% 88%;
    --sidebar-ring: 220 90% 28%;
  }

  .dark {
    --background: 220 30% 8%;
    --foreground: 220 20% 98%;

    --card: 220 30% 10%;
    --card-foreground: 220 20% 98%;

    --popover: 220 30% 10%;
    --popover-foreground: 220 20% 98%;

    --primary: 220 90% 45%;
    --primary-foreground: 0 0% 100%;

    --secondary: 220 85% 50%;
    --secondary-foreground: 0 0% 100%;

    --muted: 220 30% 18%;
    --muted-foreground: 220 20% 65%;

    --accent: 220 90% 40%;
    --accent-foreground: 0 0% 100%;

    --destructive: 0 62.8% 50%;
    --destructive-foreground: 220 20% 98%;

    --border: 220 30% 20%;
    --input: 220 30% 20%;
    --ring: 220 90% 45%;
    
    --sidebar-background: 220 30% 10%;
    --sidebar-foreground: 220 20% 90%;
    --sidebar-primary: 220 90% 45%;
    --sidebar-primary-foreground: 0 0% 100%;
    --sidebar-accent: 220 30% 15%;
    --sidebar-accent-foreground: 220 90% 45%;
    --sidebar-border: 220 30% 18%;
    --sidebar-ring: 220 90% 45%;
  }
}

@layer base {
  * {
    @apply border-border;
  }

  body {
    @apply bg-background text-foreground;
  }
}
