"use client";

import { useState } from "react";
import "./cosmic.css";
import { CosmicNav } from "./components/cosmic/cosmic-nav";
import { CosmicHero } from "./components/cosmic/cosmic-hero";
import { CosmicHow } from "./components/cosmic/cosmic-how";
import { CosmicWhy } from "./components/cosmic/cosmic-why";
import { CosmicStack } from "./components/cosmic/cosmic-stack";
import { CosmicVoices } from "./components/cosmic/cosmic-voices";
import { CosmicFAQ } from "./components/cosmic/cosmic-faq";
import { CosmicCTA } from "./components/cosmic/cosmic-cta";
import { CosmicFooter } from "./components/cosmic/cosmic-footer";
import { CosmicModal } from "./components/cosmic/cosmic-modal";

const REPO_URL = "https://github.com/Aditya-00a/Instaply";

export default function CosmicSite() {
  const [modalOpen, setModalOpen] = useState(false);
  const open = () => setModalOpen(true);
  const close = () => setModalOpen(false);

  return (
    <div className="cosmic-root">
      <CosmicNav onApply={open} repoUrl={REPO_URL} />
      <CosmicHero onApply={open} />
      <CosmicHow />
      <CosmicWhy />
      <CosmicStack />
      <CosmicVoices />
      <CosmicFAQ />
      <CosmicCTA onApply={open} repoUrl={REPO_URL} />
      <CosmicFooter repoUrl={REPO_URL} />
      <CosmicModal open={modalOpen} onClose={close} />
    </div>
  );
}
