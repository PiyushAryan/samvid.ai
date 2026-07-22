import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { BookDemoPage } from "./BookDemo";

const { calCommand } = vi.hoisted(() => ({ calCommand: vi.fn() }));

vi.mock("@calcom/embed-react", () => ({
  getCalApi: vi.fn(async () => calCommand)
}));

describe("BookDemoPage", () => {
  it("collects workflow details before showing available times", () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    render(
      <MemoryRouter>
        <BookDemoPage />
      </MemoryRouter>
    );

    const calTrigger = screen.getByText("Open Cal.com scheduler");
    const calTriggerClick = vi.spyOn(calTrigger, "click");

    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "Piyush Aryan" } });
    fireEvent.change(screen.getByLabelText(/Work email/), { target: { value: "piyush@example.com" } });
    fireEvent.change(screen.getByLabelText(/Where does contract work slow down/), {
      target: { value: "Vendor reviews and signature follow-ups" }
    });
    fireEvent.click(screen.getByRole("button", { name: /Select date & time/ }));

    expect(calTriggerClick).toHaveBeenCalledOnce();
    expect(calTrigger).toHaveAttribute("data-cal-namespace", "virtual-coffee");
    expect(calTrigger).toHaveAttribute("data-cal-link", "piyush-aryan-hrnwlm/virtual-coffee");
    expect(calTrigger.getAttribute("data-cal-config")).toContain("piyush@example.com");
  });
});
