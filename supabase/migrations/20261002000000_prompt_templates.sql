-- ============================================================
-- Prompt templates ("Discover" gallery, admin-configurable)
-- ============================================================

create table public.prompt_templates (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  category text not null default 'general',
  engine text not null default 'image' check (engine in ('image','video')),
  mode text not null default 't2i' check (mode in ('t2i','edit','t2v','i2v')),
  prompt text not null,
  negative_prompt text not null default '',
  -- [{key, label, example}] — {key} tokens in prompt are user-editable
  placeholders jsonb not null default '[]'::jsonb,
  -- sample image the admin uploaded (references bucket); shown on the card and
  -- auto-attached as a reference for edit/i2v templates
  example_image_path text,
  active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create trigger set_prompt_templates_updated_at
  before update on public.prompt_templates
  for each row execute function public.set_updated_at();

create index idx_templates_sort on public.prompt_templates (active, sort_order);

alter table public.prompt_templates enable row level security;

create policy templates_read_authenticated on public.prompt_templates
  for select to authenticated
  using (active or public.is_admin());

create policy templates_write_admin on public.prompt_templates
  for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

-- -------------------------------------------------------------- seed templates
insert into public.prompt_templates (title, category, engine, mode, prompt,
                                     negative_prompt, placeholders, sort_order) values
('Saree drape on model', 'Apparel', 'image', 'edit',
 'Dress the person in <image1> in a {color} {fabric} saree draped in {drape_style} style, matching blouse, elegant pleats, full-body shot, soft studio lighting, e-commerce catalog photography, clean {background} background, photorealistic',
 '', '[{"key":"color","label":"Saree color","example":"emerald green"},{"key":"fabric","label":"Fabric","example":"silk"},{"key":"drape_style","label":"Drape style","example":"Nivi"},{"key":"background","label":"Background","example":"white"}]', 10),

('Jewelry try-on (product on model)', 'Jewelry', 'image', 'edit',
 'Take the {jewelry_type} shown in <image1> and place it on the model in <image2>, worn naturally and photorealistically, correct scale and perspective, matching skin tone and studio lighting, keep the model pose and outfit unchanged, e-commerce catalog photography',
 '', '[{"key":"jewelry_type","label":"Jewelry type","example":"necklace"}]', 20),

('Generate a jewelry model', 'Jewelry', 'image', 't2i',
 'Full-body studio photograph of a {model_desc} fashion model wearing an elegant {jewelry_type}, neutral confident pose, hands visible, soft diffused studio lighting, plain {background} background, e-commerce product photography, photorealistic, sharp focus',
 '', '[{"key":"model_desc","label":"Model description","example":"young Indian female"},{"key":"jewelry_type","label":"Jewelry type","example":"kundan necklace set"},{"key":"background","label":"Background","example":"light grey"}]', 30),

('Product background replacement', 'Product', 'image', 'edit',
 'Replace the background of the product in <image1> with {background}, keep the product completely unchanged, professional e-commerce catalog styling, even lighting, subtle shadow under the product',
 '', '[{"key":"background","label":"New background","example":"a clean marble surface with soft gradient"}]', 40),

('Lehenga look on model', 'Apparel', 'image', 'edit',
 'Dress the person in <image1> in a {color} lehenga with {embroidery} embroidery and a matching dupatta, traditional Indian bridal styling, jewelry included, full-body shot, luxury e-commerce photography, clean studio background, photorealistic',
 '', '[{"key":"color","label":"Lehenga color","example":"deep red"},{"key":"embroidery","label":"Embroidery style","example":"zari"}]', 50),

('Jewelry showcase video', 'Video', 'video', 'i2v',
 'Slow elegant 360-degree rotation showcase of the jewelry piece, soft studio lighting with gentle highlights moving across the surface, luxurious mood, seamless loop, e-commerce product video',
 '', '[]', 60);
