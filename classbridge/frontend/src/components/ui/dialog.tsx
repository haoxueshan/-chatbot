import * as Primitive from "@radix-ui/react-dialog";
import { useRef, type ReactNode } from "react";
import { cn } from "../../lib/utils";

// Radix supplies focus trapping, Escape handling, inert background and scroll lock.
// The caller retains ownership of submission state and business actions.
export function Dialog({
  children,
  title,
  description,
  close,
  busy = false,
  className,
}: {
  children: ReactNode;
  title: string;
  description?: string;
  close: () => void;
  busy?: boolean;
  className?: string;
}) {
  const opener = useRef(
    typeof document === "undefined"
      ? null
      : (document.activeElement as HTMLElement | null),
  );
  return (
    <Primitive.Root
      open
      onOpenChange={(open) => {
        if (!open && !busy) close();
      }}
    >
      <Primitive.Portal>
        <Primitive.Overlay className="dialog-overlay" />
        <Primitive.Content
          className={cn("ui-dialog modal", className)}
          {...(!description ? { "aria-describedby": undefined } : {})}
          onEscapeKeyDown={(event) => {
            if (busy) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (busy) event.preventDefault();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            // A drawer can open another dialog in the same commit. Its delayed
            // restoration must not steal focus from the newly opened form.
            if (document.querySelector('[role="dialog"][data-state="open"]'))
              return;
            if (opener.current?.isConnected) opener.current.focus();
            else
              document
                .querySelector<HTMLButtonElement>(
                  "[data-dialog-fallback-focus]",
                )
                ?.focus();
          }}
        >
          <Primitive.Title className="sr-only">{title}</Primitive.Title>
          {description && (
            <Primitive.Description className="sr-only">
              {description}
            </Primitive.Description>
          )}
          {children}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
