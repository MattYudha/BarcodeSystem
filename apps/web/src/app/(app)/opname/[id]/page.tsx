"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense } from "react";

import { AdminOnly, LoadingBlock, PageHeader } from "@/components/app/common";
import { Button } from "@/components/ui/button";

import { OpnameDetail } from "../opname-detail";

function Detail() {
  const { id } = useParams<{ id: string }>();
  return <OpnameDetail id={Number(id)} />;
}

export default function OpnameDetailPage() {
  return (
    <AdminOnly>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link href="/opname"><ArrowLeft /> Stock opname</Link>
      </Button>
      <PageHeader title="Detail Stock Opname" />
      <Suspense fallback={<LoadingBlock />}>
        <Detail />
      </Suspense>
    </AdminOnly>
  );
}
