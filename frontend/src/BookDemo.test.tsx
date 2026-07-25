import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BookDemoPage } from "./BookDemo";

const { calCommand, getCalApi } = vi.hoisted(() => ({
  calCommand: vi.fn(),
  getCalApi: vi.fn()
}));

vi.mock("@calcom/embed-react", () => ({
  getCalApi
}));

describe("BookDemoPage", () => {
  beforeEach(() => {
    calCommand.mockReset();
    getCalApi.mockReset();
    getCalApi.mockResolvedValue(calCommand);
  });

  it("collects workflow details before showing available times", async () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    render(<BookDemoPage />);

    const submitButton = await screen.findByRole("button", { name: /Select date & time/ });

    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "Piyush Aryan" } });
    fireEvent.change(screen.getByLabelText(/Work email/), { target: { value: "piyush@example.com" } });
    fireEvent.change(screen.getByLabelText(/Where does contract work slow down/), {
      target: { value: "Vendor reviews and signature follow-ups" }
    });
    fireEvent.click(submitButton);

    expect(calCommand).toHaveBeenCalledWith(
      "modal",
      expect.objectContaining({
        calLink: "piyush-aryan-hrnwlm/virtual-coffee",
        config: expect.objectContaining({
          name: "Piyush Aryan",
          email: "piyush@example.com",
          notes: expect.stringContaining("Vendor reviews and signature follow-ups")
        })
      })
    );
  });

  it("offers the direct booking page if the embed cannot load", async () => {
    getCalApi.mockRejectedValueOnce(new Error("Cal embed unavailable"));
    render(<BookDemoPage />);

    const fallbackLink = await screen.findByRole("link", { name: /Open booking calendar/ });
    expect(fallbackLink).toHaveAttribute(
      "href",
      "https://cal.com/piyush-aryan-hrnwlm/virtual-coffee"
    );
  });

  it("keeps submission unavailable while the calendar is initializing", async () => {
    getCalApi.mockImplementationOnce(() => new Promise(() => undefined));
    render(<BookDemoPage />);

    expect(screen.getByRole("button", { name: /Preparing calendar/ })).toBeDisabled();
    await waitFor(() => {
      expect(screen.getByText("Loading secure scheduling")).toBeInTheDocument();
    });
  });
});
