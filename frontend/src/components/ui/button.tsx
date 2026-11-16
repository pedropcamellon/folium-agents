import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Button as BaseButton } from "@base-ui/react/button";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center whitespace-nowrap rounded-sm border font-bold transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-[#f0c64d] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-[0.55]",
  {
    variants: {
      variant: {
        default: "border-[#1769aa] bg-[#1769aa] text-white hover:bg-[#0e558f]",
        secondary:
          "border-[#8b9aaa] bg-white text-[#30455b] hover:bg-[#edf2f6]",
      },
      size: {
        default: "min-h-[2.7rem] px-4 py-[0.65rem]",
        sm: "min-h-[2.25rem] px-[0.7rem] py-[0.45rem]",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export type ButtonProps = React.ComponentProps<typeof BaseButton> &
  VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return (
    <BaseButton
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}
